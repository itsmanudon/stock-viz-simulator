"""`/v1/symbols/{ticker}/bars` — OHLCV history for charts.

``interval=1d`` returns stored daily bars. ``1wk`` and ``1mo`` (A1.4a) are
resampled on read from them (``services/bars/resample.py``): ``limit`` counts
output bars, ``from``/``to`` select bars by their timestamp (the period's
last stored session) and every bar covers its whole period. The newest bar
carries ``partial: true`` while its week or month is not over at the venue.

``adjustment=raw`` (A3.1) reads the exchange's own numbers from ``eod_raw``
instead of the split-adjusted ``price_bars`` (``services/bars/raw.py``), with
the same intervals and filters; an instrument with no ``eod_raw`` row is 409.

``interval=1m|5m|15m|30m|60m`` (A6.2) reads ``intraday_bars``
(``services/bars/intraday.py``): stored minutes, resampled on read within each
session's trading spans, 60-minute bars from the minutes where a session has
them and from the stored hourly bars where it has none. ``from``/``to`` select
by the bar's open (naive UTC, or any offset); ``feed`` picks a stored feed
(default: the best stored). The newest bar is ``partial`` while it is not
closed. 404 with the reason when the symbol has no bars to build the interval
from. Intraday bars are adjusted only (``adjustment=raw`` is 409).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlmodel import Session, select

from stockviz.db import get_session
from stockviz.limiter import limiter
from stockviz.models import PriceBar, Symbol
from stockviz.schemas import BarOut
from stockviz.services.bars.intraday import (
    INTERVAL_MINUTES,
    IntradayOut,
    NoIntradayData,
    coverage,
    load_intraday,
    pick_feed,
)
from stockviz.services.bars.load import load_resampled
from stockviz.services.bars.raw import RawBar, has_raw, load_raw_daily, load_raw_resampled
from stockviz.services.bars.resample import ResampledBar
from stockviz.services.instruments import instrument_of, resolve_symbol
from stockviz.services.markets.calendar import venue_for_ticker

router = APIRouter(prefix="/v1/symbols", tags=["bars"])

SessionDep = Annotated[Session, Depends(get_session)]

MAX_BARS = 5000


@router.get("/{ticker}/bars", response_model=list[BarOut])
@limiter.limit("60/minute")
def get_bars(
    request: Request,
    ticker: str,
    session: SessionDep,
    interval: Annotated[str, Query(pattern=r"^(1d|1wk|1mo|1m|5m|15m|30m|60m)$")] = "1d",
    from_: Annotated[datetime | None, Query(alias="from")] = None,
    to: Annotated[datetime | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_BARS)] = 1000,
    adjustment: Annotated[Literal["adjusted", "raw"], Query()] = "adjusted",
    feed: Annotated[Literal["iex", "sip", "kite", "file", "replayed"] | None, Query()] = None,
) -> list[PriceBar] | list[BarOut]:
    ticker = ticker.upper()
    if session.get(Symbol, ticker) is None:
        raise HTTPException(status_code=404, detail=f"Symbol {ticker!r} not found")

    if interval in INTERVAL_MINUTES:
        if adjustment == "raw":
            raise HTTPException(
                status_code=409,
                detail="Intraday bars are stored as loaded; ask for adjustment=adjusted.",
            )
        bars = intraday_bars(session, ticker, interval, feed, from_, to, limit)
        return [intraday_out(b) for b in bars]

    if adjustment == "raw":
        return _raw_bars(session, ticker, interval, from_, to, limit)

    if interval != "1d":
        bars = load_resampled(
            session,
            ticker,
            interval,
            bars_wanted=limit,
            to=to.date() if to is not None else None,
        )
        if from_ is not None:
            bars = [b for b in bars if b.ts.date() >= from_.date()]
        if to is not None:
            bars = [b for b in bars if b.ts.date() <= to.date()]
        return [_out(b) for b in bars[-limit:]]

    stmt = select(PriceBar).where(
        PriceBar.instrument_id == instrument_of(ticker), PriceBar.interval == interval
    )
    if from_ is not None:
        stmt = stmt.where(PriceBar.ts >= from_)
    if to is not None:
        stmt = stmt.where(PriceBar.ts <= to)
    # Newest-first so a ``limit`` returns the most recent bars; reverse for the
    # client so charts get oldest-first.
    stmt = stmt.order_by(PriceBar.ts.desc()).limit(limit)  # type: ignore[attr-defined]

    rows = list(session.exec(stmt).all())
    rows.reverse()
    return rows


def _raw_bars(
    session: Session,
    ticker: str,
    interval: str,
    from_: datetime | None,
    to: datetime | None,
    limit: int,
) -> list[BarOut]:
    if not has_raw(session, ticker):
        raise HTTPException(
            status_code=409,
            detail=(
                f"Only adjusted prices are stored for {ticker}: there are no raw exchange "
                "rows (eod_raw) for it. Ask for adjustment=adjusted."
            ),
        )
    if interval == "1d":
        daily = load_raw_daily(
            session,
            ticker,
            from_=from_.date() if from_ is not None else None,
            to=to.date() if to is not None else None,
            sessions=limit,
        )
        return [_raw_out(b) for b in daily]
    bars = load_raw_resampled(
        session,
        ticker,
        interval,
        bars_wanted=limit,
        to=to.date() if to is not None else None,
    )
    if from_ is not None:
        bars = [b for b in bars if b.ts.date() >= from_.date()]
    if to is not None:
        bars = [b for b in bars if b.ts.date() <= to.date()]
    return [_out(b) for b in bars[-limit:]]


def _raw_out(bar: RawBar) -> BarOut:
    return BarOut(
        ts=bar.ts,
        open=bar.open,
        high=bar.high,
        low=bar.low,
        close=bar.close,
        volume=bar.volume,
        source=bar.source,
        adjustment_semantics=bar.adjustment_semantics,
    )


def _out(bar: ResampledBar) -> BarOut:
    return BarOut(
        ts=bar.ts,
        open=bar.open,
        high=bar.high,
        low=bar.low,
        close=bar.close,
        volume=bar.volume,
        source=bar.source,
        adjustment_semantics=bar.adjustment_semantics,
        sessions=bar.sessions,
        partial=bar.partial,
    )


def naive_utc(value: datetime | None) -> datetime | None:
    """A query instant as naive UTC (a value without an offset is UTC)."""
    if value is None or value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def intraday_bars(
    session: Session,
    ticker: str,
    interval: str,
    feed: str | None,
    from_: datetime | None,
    to: datetime | None,
    bars_wanted: int,
) -> list[IntradayOut]:
    """The intraday bars a route asked for, or 404 with the reason."""
    instrument = resolve_symbol(session, ticker)
    if instrument is None or instrument.id is None:
        raise HTTPException(status_code=404, detail=f"Symbol {ticker!r} not found")
    try:
        chosen = pick_feed(coverage(session, instrument.id), interval, feed, ticker)
    except NoIntradayData as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return load_intraday(
        session,
        instrument.id,
        interval,
        venue=venue_for_ticker(ticker),
        feed=chosen,
        bars_wanted=bars_wanted,
        from_=naive_utc(from_),
        to=naive_utc(to),
    )


def intraday_out(bar: IntradayOut) -> BarOut:
    return BarOut(
        ts=bar.ts,
        open=bar.open,
        high=bar.high,
        low=bar.low,
        close=bar.close,
        volume=bar.volume,
        source=bar.source,
        partial=bar.partial,
        closed_at=bar.closed_at,
        session_date=bar.session_date,
        feed=bar.feed,
        badge=bar.badge,
        minutes=bar.minutes,
    )
