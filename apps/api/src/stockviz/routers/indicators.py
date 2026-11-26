"""`/v1/symbols/{ticker}/indicators` — technical indicators on demand.

Accepts a comma-separated ``names`` list (``sma_20,rsi_14,macd,bb_20_2``):
any indicator in ``services/indicators/engine.REGISTRY`` with its parameters
joined by ``_`` (defaults when omitted). ``/v1/indicators/catalog`` lists them.
The router fetches the bar series once, runs each requested indicator, and
returns a single bundle so the chart only has to make one round-trip.

``interval=1wk|1mo`` (A1.4a) runs the same registry on bars resampled from
the daily ones, with the same warm-up rule counted in output bars. A partial
newest bar (its week or month not over at the venue) is left out of the
inputs: no indicator value is computed on a period still running, and the
response names the bar it left out in ``partial_bar_excluded``.

``interval=1m|5m|15m|30m|60m`` (A6.2) runs the registry on the intraday bars
the bars route returns (same feed rule, same resampling), warmed up on the
intraday bars before the window, never on daily ones. A partial newest bar is
left out the same way. Studies that read the venue index (the RS line) get
no index on intraday bars (its daily close would be a value from later in
the day), so their series is empty.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlmodel import Session, select

from stockviz.db import get_session
from stockviz.limiter import limiter
from stockviz.models import PriceBar, Symbol
from stockviz.routers.bars import intraday_bars, naive_utc
from stockviz.schemas import (
    ChecklistEvidenceOut,
    IndicatorCatalogItemOut,
    IndicatorParamOut,
    IndicatorSignalOut,
    IndicatorsOut,
    UniverseOut,
)
from stockviz.services.backtest.universe import evidence_universe
from stockviz.services.bars.intraday import INTERVAL_MINUTES
from stockviz.services.bars.load import load_resampled
from stockviz.services.indicator_view import compute_bundle
from stockviz.services.indicators import engine
from stockviz.services.indicators.evidence import compiled_signals, latest_by_indicator
from stockviz.services.indicators.signals import SIGNALS
from stockviz.services.instruments import instrument_of

router = APIRouter(prefix="/v1/symbols", tags=["indicators"])
catalog_router = APIRouter(prefix="/v1/indicators", tags=["indicators"])

SessionDep = Annotated[Session, Depends(get_session)]

MAX_BARS = 5000
"""Hard cap on the bar window we'll feed indicators. Matches the bars router."""

MAX_WARMUP = 5000
"""Cap on extra bars loaded before the window (the largest lookback is ADX at
20 x n; a 500-period ADX is not a request worth serving)."""


def _needs_bench(parsed: list[engine.Request]) -> bool:
    return any(r.spec.needs_benchmark for r in parsed)


def _parse_names(raw: str) -> list[engine.Request]:
    """``"sma_20,macd,bb_20_2"`` -> engine requests (Phase 6.1 registry)."""
    parsed: list[engine.Request] = []
    for chunk in raw.split(","):
        if not chunk.strip():
            continue
        try:
            parsed.append(engine.parse(chunk))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not parsed:
        raise HTTPException(status_code=400, detail="At least one indicator name is required")
    if max(r.lookback for r in parsed) > MAX_WARMUP:
        raise HTTPException(status_code=400, detail="Indicator lookback too long")
    return parsed


@catalog_router.get("/catalog", response_model=list[IndicatorCatalogItemOut])
@limiter.limit("60/minute")
def get_catalog(request: Request, session: SessionDep) -> list[IndicatorCatalogItemOut]:
    """Every indicator the engine offers, with its parameters (names,
    defaults, bounds) and, for studies with a canonical signal, the signal
    rule and its latest evidence grade (A3.4)."""
    rules = compiled_signals()
    rows = latest_by_indicator(session)
    note = evidence_universe().note
    out: list[IndicatorCatalogItemOut] = []
    for s in engine.REGISTRY.values():
        signal = None
        if s.key in SIGNALS:
            row = rows.get(s.key)
            evidence = (
                ChecklistEvidenceOut(
                    grade=row.grade,  # type: ignore[arg-type]
                    n_events=row.n_events,
                    symbols=row.symbols,
                    horizon=row.horizon,
                    window_start=row.window_start,
                    window_end=row.window_end,
                    mean_excess=row.mean_excess,
                    t_stat=row.t_stat,
                    hit_rate=row.hit_rate,
                    mean_net_return=row.mean_net_return,
                    base_rate=row.base_rate,
                    overlapping_skipped=row.overlapping_skipped,
                    fee_schedules={k: int(v) for k, v in (row.fee_schedules or {}).items()},
                    universe=UniverseOut(
                        name=row.universe,
                        point_in_time=row.point_in_time,
                        survivorship_biased=row.survivorship_biased,
                        note=note,
                    ),
                    computed_at=row.computed_at,
                )
                if row is not None
                else None
            )
            signal = IndicatorSignalOut(
                rule=rules[s.key].canonical_text,
                hash=rules[s.key].hash,
                description=SIGNALS[s.key].description,
                source=SIGNALS[s.key].source,
                evidence=evidence,
            )
        out.append(
            IndicatorCatalogItemOut(
                key=s.key,
                label=s.label,
                params=list(s.params),
                defaults=[float(d) for d in s.defaults],
                outputs=list(s.outputs),
                pane=s.pane,
                group=s.group,
                parameters=[IndicatorParamOut(**p.schema()) for p in s.parameters],  # type: ignore[arg-type]
                default_key=s.default_key(),
                anchored=s.anchored,
                description=s.description,
                source=s.source,
                signal=signal,
            )
        )
    return out


def _bench_closes(session: Session, ticker: str) -> pd.Series | None:
    """The venue index's daily closes for the RS line (A3.4), or None."""
    from stockviz.services.event_study import benchmark_for

    bench = benchmark_for(ticker)
    if bench is None:
        return None
    rows = session.exec(
        select(PriceBar)
        .where(PriceBar.instrument_id == instrument_of(bench), PriceBar.interval == "1d")
        .order_by(PriceBar.ts)  # type: ignore[arg-type]
    ).all()
    return pd.Series(
        [float(r.close) for r in rows],
        index=pd.DatetimeIndex([r.ts for r in rows]),
        dtype=float,
    )


@router.get("/{ticker}/indicators", response_model=IndicatorsOut)
@limiter.limit("60/minute")
def get_indicators(
    request: Request,
    ticker: str,
    session: SessionDep,
    names: Annotated[str, Query(description="e.g. sma_20,rsi_14,macd,bb_20_2")],
    interval: Annotated[str, Query(pattern=r"^(1d|1wk|1mo|1m|5m|15m|30m|60m)$")] = "1d",
    from_: Annotated[datetime | None, Query(alias="from")] = None,
    to: Annotated[datetime | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_BARS)] = 1000,
    feed: Annotated[Literal["iex", "sip", "kite", "file"] | None, Query()] = None,
) -> IndicatorsOut:
    """Indicators over a window of bars, warmed up on the bars before it (RS-1).

    The window is the last ``limit`` bars within ``from``/``to``. The bars each
    indicator needs before that window are loaded too, so a value on a given
    day is the same whatever window the chart asks for.
    """
    ticker = ticker.upper()
    if session.get(Symbol, ticker) is None:
        raise HTTPException(status_code=404, detail=f"Symbol {ticker!r} not found")

    parsed = _parse_names(names)
    if interval in INTERVAL_MINUTES:
        return _intraday_indicators(session, ticker, interval, feed, parsed, from_, to, limit)
    if interval != "1d":
        return _resampled_indicators(session, ticker, interval, parsed, from_, to, limit)

    stmt = select(PriceBar).where(
        PriceBar.instrument_id == instrument_of(ticker), PriceBar.interval == interval
    )
    if from_ is not None:
        stmt = stmt.where(PriceBar.ts >= from_)
    if to is not None:
        stmt = stmt.where(PriceBar.ts <= to)
    stmt = stmt.order_by(PriceBar.ts.desc()).limit(limit)  # type: ignore[attr-defined]
    rows = list(session.exec(stmt).all())
    rows.reverse()

    window_start = rows[0].ts if rows else None
    warmup: list[PriceBar] = []
    lookback = max(r.lookback for r in parsed)
    if rows and lookback > 0:
        warmup = list(
            session.exec(
                select(PriceBar)
                .where(
                    PriceBar.instrument_id == instrument_of(ticker),
                    PriceBar.interval == interval,
                    PriceBar.ts < rows[0].ts,
                )
                .order_by(PriceBar.ts.desc())  # type: ignore[attr-defined]
                .limit(lookback)
            ).all()
        )
        warmup.reverse()

    ohlcv = [(r.ts, r.open, r.high, r.low, r.close, r.volume) for r in warmup + rows]
    return compute_bundle(
        ticker,
        interval,
        parsed,
        ohlcv,
        window_start=window_start,
        warmup_bars=len(warmup),
        bench=_bench_closes(session, ticker) if _needs_bench(parsed) else None,
    )


def _resampled_indicators(
    session: Session,
    ticker: str,
    interval: str,
    parsed: list[engine.Request],
    from_: datetime | None,
    to: datetime | None,
    limit: int,
) -> IndicatorsOut:
    lookback = max(r.lookback for r in parsed)
    bars = load_resampled(
        session,
        ticker,
        interval,
        bars_wanted=limit + lookback,
        to=to.date() if to is not None else None,
    )
    excluded = None
    if bars and bars[-1].partial:
        excluded = bars[-1].ts
        bars = bars[:-1]
    in_range = [
        i
        for i, b in enumerate(bars)
        if (from_ is None or b.ts.date() >= from_.date())
        and (to is None or b.ts.date() <= to.date())
    ][-limit:]
    if in_range:
        first, last = in_range[0], in_range[-1]
        rows, warmup = bars[first : last + 1], bars[max(0, first - lookback) : first]
    else:
        rows, warmup = [], []
    ohlcv = [(r.ts, r.open, r.high, r.low, r.close, r.volume) for r in warmup + rows]
    bundle = compute_bundle(
        ticker,
        interval,
        parsed,
        ohlcv,
        window_start=rows[0].ts if rows else None,
        warmup_bars=len(warmup),
        bench=_bench_closes(session, ticker) if _needs_bench(parsed) else None,
    )
    return bundle.model_copy(update={"interval": interval, "partial_bar_excluded": excluded})


def _intraday_indicators(
    session: Session,
    ticker: str,
    interval: str,
    feed: str | None,
    parsed: list[engine.Request],
    from_: datetime | None,
    to: datetime | None,
    limit: int,
) -> IndicatorsOut:
    """A6.2: the registry on intraday bars, warmed up on earlier intraday bars."""
    lookback = max(r.lookback for r in parsed)
    start, end = naive_utc(from_), naive_utc(to)
    # Load from the start of the warm-up: the window's bars plus ``lookback``
    # before them (``from`` filters after, so the warm-up is not cut off).
    bars = intraday_bars(session, ticker, interval, feed, None, end, limit + lookback + 1)
    excluded = None
    if bars and bars[-1].partial:
        excluded = bars[-1].ts
        bars = bars[:-1]
    in_range = [i for i, b in enumerate(bars) if start is None or b.ts >= start][-limit:]
    if in_range:
        first, last = in_range[0], in_range[-1]
        rows, warmup = bars[first : last + 1], bars[max(0, first - lookback) : first]
    else:
        rows, warmup = [], []
    ohlcv = [(r.ts, r.open, r.high, r.low, r.close, r.volume) for r in warmup + rows]
    bundle = compute_bundle(
        ticker,
        interval,
        parsed,
        ohlcv,
        window_start=rows[0].ts if rows else None,
        warmup_bars=len(warmup),
        bench=None,
    )
    return bundle.model_copy(
        update={
            "interval": interval,
            "partial_bar_excluded": excluded,
            "feed": (rows or bars)[0].feed if (rows or bars) else None,
        }
    )
