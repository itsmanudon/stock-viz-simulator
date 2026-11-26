"""`GET /v1/symbols/{ticker}/avwap` (A3.3, M2.5): an anchored VWAP.

Public, 60/min like the other public reads. ``anchor=YYYY-MM-DD`` must lie
between the symbol's first and last stored daily bar (422 otherwise); the
sums start at the first daily bar on or after it (``anchor_bar``).
``interval=1d|1wk|1mo``: always computed from daily bars; on weekly and
monthly it is sampled at each period's last stored session, which is the
weekly/monthly bar's ``ts`` on the bars route. ``bands=0|1|2`` adds the
+-1 (and +-2) volume-weighted standard deviation bands. The maths is
``services/avwap.py`` (float64, rounded to 4 decimals here), the same code
the Rule DSL's ``avwap()`` runs.

**Intraday (A6.2).** ``interval=1m|5m|15m|30m`` sums from the **1-minute**
bars and samples each chart bar at its last minute, keyed by the bar's open
(the bars route's ``ts``). ``interval=60m`` sums over the 60-minute chart's
own bars (which reach back to the hourly files). The anchor is an instant:
``anchor_at`` (ISO, naive = UTC), the sums start at the first bar opening at
or after it; or ``anchor`` (a date), which means that session's open (how a
date-anchored drawing lands on an intraday chart). Up to
:data:`MAX_INTRADAY_MINUTES` minutes are summed (422 past it: anchor later,
or use 60m). The daily AVWAP is unchanged.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Annotated, Literal

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlmodel import Session, col, select

from stockviz.db import get_session
from stockviz.limiter import limiter
from stockviz.models import PriceBar, Symbol
from stockviz.routers.bars import naive_utc
from stockviz.schemas import AvwapOut, AvwapPointOut
from stockviz.services import avwap
from stockviz.services.bars.intraday import (
    INTERVAL_MINUTES,
    NoIntradayData,
    Row,
    coverage,
    load_intraday,
    minute_rows_from,
    pick_feed,
    resample_minutes,
    session_open,
)
from stockviz.services.bars.resample import bar_date, period_start
from stockviz.services.drawings import bar_range
from stockviz.services.instruments import instrument_of, resolve_symbol
from stockviz.services.markets.calendar import venue_for_ticker

router = APIRouter(prefix="/v1/symbols", tags=["avwap"])

SessionDep = Annotated[Session, Depends(get_session)]


def _r(value: float) -> float | None:
    return None if not np.isfinite(value) else round(float(value), avwap.API_DECIMALS)


@router.get("/{ticker}/avwap", response_model=AvwapOut)
@limiter.limit("60/minute")
def get_avwap(
    request: Request,
    ticker: str,
    session: SessionDep,
    anchor: Annotated[date | None, Query(description="Anchor date, YYYY-MM-DD")] = None,
    interval: Annotated[
        Literal["1d", "1wk", "1mo", "1m", "5m", "15m", "30m", "60m"], Query()
    ] = "1d",
    bands: Annotated[int, Query(ge=0, le=2)] = 0,
    anchor_at: Annotated[datetime | None, Query(description="Intraday anchor instant")] = None,
    feed: Annotated[Literal["iex", "sip", "kite", "file"] | None, Query()] = None,
) -> AvwapOut:
    ticker = ticker.upper()
    instrument = resolve_symbol(session, ticker)
    if session.get(Symbol, ticker) is None or instrument is None or instrument.id is None:
        raise HTTPException(status_code=404, detail=f"Symbol {ticker!r} not found")
    if interval in INTERVAL_MINUTES:
        return _intraday_avwap(
            session, ticker, instrument.id, interval, anchor, anchor_at, bands, feed
        )
    if anchor is None:
        raise HTTPException(status_code=422, detail="anchor (YYYY-MM-DD) is required")
    first, last = bar_range(session, instrument.id, ticker)
    if first is None or last is None:
        raise HTTPException(status_code=422, detail=f"No stored daily bars for {ticker}")
    if not first <= anchor <= last:
        raise HTTPException(
            status_code=422,
            detail=(
                f"The anchor {anchor.isoformat()} must be between {first.isoformat()} and "
                f"{last.isoformat()} (the stored daily bars)"
            ),
        )
    venue = venue_for_ticker(ticker)
    rows = list(
        session.exec(
            select(PriceBar)
            .where(
                PriceBar.instrument_id == instrument_of(ticker),
                PriceBar.interval == "1d",
                col(PriceBar.ts) >= datetime.combine(anchor - timedelta(days=1), time.min),
            )
            .order_by(col(PriceBar.ts))
        ).all()
    )
    rows = [r for r in rows if bar_date(r.ts, venue) >= anchor]
    if not rows:  # pragma: no cover - the range check above makes this unreachable
        raise HTTPException(status_code=422, detail="No bar on or after the anchor")
    days = [bar_date(r.ts, venue) for r in rows]
    series = avwap.compute(
        days,
        np.array([float(r.high) for r in rows]),
        np.array([float(r.low) for r in rows]),
        np.array([float(r.close) for r in rows]),
        np.array([float(r.volume) for r in rows]),
        anchor,
    )
    if interval == "1d":
        picks = list(range(len(rows)))
    else:
        keys = [period_start(d, interval) for d in days]
        picks = [i for i, _v in avwap.sample_last_of_period(keys, series.vwap)]
    points: list[AvwapPointOut] = []
    for i in picks:
        vwap = _r(series.vwap[i])
        if vwap is None:
            continue  # no volume yet since the anchor
        point = AvwapPointOut(ts=rows[i].ts, vwap=vwap)
        if bands >= 1:
            point.upper1, point.lower1 = _r(series.band(1)[i]), _r(series.band(-1)[i])
        if bands >= 2:
            point.upper2, point.lower2 = _r(series.band(2)[i]), _r(series.band(-2)[i])
        points.append(point)
    return AvwapOut(
        ticker=ticker,
        anchor=anchor,
        anchor_bar=days[0],
        interval=interval,
        bands=bands,
        decimals=avwap.API_DECIMALS,
        points=points,
    )


MAX_INTRADAY_MINUTES = 100_000
"""Most 1-minute bars an intraday AVWAP sums (about 266 NSE sessions)."""

MAX_INTRADAY_HOURS = 5_000
"""Most 60-minute bars a 60m AVWAP sums."""


def _intraday_avwap(
    session: Session,
    ticker: str,
    instrument_id: int,
    interval: str,
    anchor: date | None,
    anchor_at: datetime | None,
    bands: int,
    feed: str | None,
) -> AvwapOut:
    venue = venue_for_ticker(ticker)
    try:
        chosen = pick_feed(coverage(session, instrument_id), interval, feed, ticker)
    except NoIntradayData as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if anchor_at is not None:
        start = naive_utc(anchor_at)
        assert start is not None
    elif anchor is not None:
        opened = session_open(anchor, venue)
        start = opened if opened is not None else datetime.combine(anchor, time.min)
    else:
        raise HTTPException(status_code=422, detail="anchor or anchor_at is required")

    if interval == "60m":
        bars = load_intraday(
            session,
            instrument_id,
            "60m",
            venue=venue,
            feed=chosen,
            bars_wanted=MAX_INTRADAY_HOURS + 1,
            from_=start,
        )
        if len(bars) > MAX_INTRADAY_HOURS:
            raise HTTPException(
                status_code=422,
                detail=f"An AVWAP sums at most {MAX_INTRADAY_HOURS} 60-minute bars; anchor later.",
            )
        base = [(b.ts, b.high, b.low, b.close, b.volume) for b in bars]
        keys = [b.ts for b in bars]
        computed_from = "60m"
    else:
        rows: list[Row] = minute_rows_from(
            session, instrument_id, chosen, start, limit=MAX_INTRADAY_MINUTES
        )
        if len(rows) > MAX_INTRADAY_MINUTES:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"An intraday AVWAP sums at most {MAX_INTRADAY_MINUTES} minute bars; "
                    "anchor later, or use 60m."
                ),
            )
        base = [(r[0], r[2], r[3], r[4], r[5]) for r in rows]
        # Each minute's chart bar: the bucket it falls in (the bars route's ts).
        keys = (
            [r[0] for r in rows]
            if interval == "1m"
            else _bucket_keys(rows, interval, venue, chosen)
        )
        computed_from = "1m"
    if not base:
        raise HTTPException(
            status_code=422,
            detail=f"No intraday bar of {ticker} opens at or after the anchor",
        )
    series = avwap.compute_from(
        np.array([float(b[1]) for b in base]),
        np.array([float(b[2]) for b in base]),
        np.array([float(b[3]) for b in base]),
        np.array([float(b[4]) for b in base]),
        0,
    )
    picks = [i for i, _v in avwap.sample_last_of_period(keys, series.vwap)]
    points: list[AvwapPointOut] = []
    for i in picks:
        vwap = _r(series.vwap[i])
        if vwap is None:
            continue
        point = AvwapPointOut(ts=keys[i], vwap=vwap)
        if bands >= 1:
            point.upper1, point.lower1 = _r(series.band(1)[i]), _r(series.band(-1)[i])
        if bands >= 2:
            point.upper2, point.lower2 = _r(series.band(2)[i]), _r(series.band(-2)[i])
        points.append(point)
    first = base[0][0]
    return AvwapOut(
        ticker=ticker,
        anchor=anchor if anchor is not None else first.date(),
        anchor_bar=first.date(),
        interval=interval,  # type: ignore[arg-type]
        bands=bands,
        computed_from=computed_from,  # type: ignore[arg-type]
        anchor_at=start,
        anchor_bar_at=first,
        feed=chosen,
        decimals=avwap.API_DECIMALS,
        points=points,
    )


def _bucket_keys(rows: list[Row], interval: str, venue: str, feed: str) -> list[datetime]:
    """Each minute's chart-bar open on ``interval`` (minutes outside a session dropped
    by the resampler are keyed by their own open)."""
    bars = resample_minutes(rows, interval, venue=venue, feed=feed)
    keys: list[datetime] = []
    j = 0
    for row in rows:
        while j + 1 < len(bars) and bars[j + 1].ts <= row[0]:
            j += 1
        keys.append(bars[j].ts if bars and bars[j].ts <= row[0] < bars[j].closed_at else row[0])
    return keys
