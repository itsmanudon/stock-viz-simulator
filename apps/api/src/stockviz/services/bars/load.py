"""Load enough daily bars to return ``n`` weekly or monthly bars (A1.4a)."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

from sqlmodel import Session, col, select

from stockviz.models import PriceBar
from stockviz.services.bars.resample import (
    MAX_SESSIONS_PER_PERIOD,
    ResampledBar,
    period_end,
    resample,
)
from stockviz.services.instruments import instrument_of
from stockviz.services.markets.calendar import venue_for_ticker


def now_utc() -> datetime:
    """The clock the partial rule reads; tests patch it."""
    return datetime.now(UTC)


def load_resampled(
    session: Session,
    ticker: str,
    interval: str,
    *,
    bars_wanted: int,
    to: date | None = None,
    now: datetime | None = None,
) -> list[ResampledBar]:
    """The newest resampled bars of ``ticker`` up to ``to``'s period, oldest first.

    Loads ``(bars_wanted + 1) x`` the most sessions a period can hold, newest
    first, so at least ``bars_wanted`` whole periods are covered. When that cap
    was reached the oldest period may be cut short, so it is dropped. Every
    returned bar covers its whole period as stored; a ``to`` inside a period
    loads that period to its end (callers filter by the bar's timestamp).
    """
    cap = (bars_wanted + 1) * MAX_SESSIONS_PER_PERIOD[interval]
    stmt = select(PriceBar).where(
        PriceBar.instrument_id == instrument_of(ticker), PriceBar.interval == "1d"
    )
    if to is not None:
        end = datetime.combine(period_end(to, interval) + timedelta(days=1), time.min)
        stmt = stmt.where(col(PriceBar.ts) < end)
    rows = list(session.exec(stmt.order_by(col(PriceBar.ts).desc()).limit(cap)).all())
    rows.reverse()
    bars = resample(rows, interval, venue=venue_for_ticker(ticker), now=now or now_utc())
    if len(rows) == cap and bars:
        bars = bars[1:]
    return bars


__all__ = ["load_resampled", "now_utc"]
