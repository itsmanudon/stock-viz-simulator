"""Raw exchange prices for charts (A3.1, M2.3).

``price_bars`` hold split-adjusted daily bars. ``eod_raw`` (A1.1) holds the
NSE cash bhavcopy as the exchange published it, per instrument, session and
series. ``GET /v1/symbols/{t}/bars?adjustment=raw`` reads these instead:

- one bar per session: when a session has several series, the first of
  :data:`RAW_SERIES_ORDER` wins (EQ, then BE, BZ, SM, ST), as for delivery;
- the bar's timestamp is the session date at midnight, the same naive venue
  label the daily ``price_bars`` carry, so weekly and monthly bars resample
  from them with the same rules (``services/bars/resample.py``);
- ``source`` is the row's own and ``adjustment_semantics`` is ``"raw"``.

An instrument with no ``eod_raw`` row has no raw prices; the router answers
409 for it, and ``has_raw`` on the symbol detail tells the web to disable the
toggle. Nothing here adjusts or fills gaps.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal

from sqlmodel import Session, col, select

from stockviz.models.eod import EodRaw
from stockviz.services.bars.resample import (
    MAX_SESSIONS_PER_PERIOD,
    ResampledBar,
    period_end,
    resample,
)
from stockviz.services.dsl.data import DELIVERY_SERIES_ORDER
from stockviz.services.instruments import instrument_of
from stockviz.services.markets.calendar import venue_for_ticker

RAW = "raw"
RAW_SERIES_ORDER = DELIVERY_SERIES_ORDER
"""When ``eod_raw`` holds several series for a session, the first here wins."""


@dataclass(frozen=True)
class RawBar:
    ts: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    source: str | None
    series: str
    adjustment_semantics: str = RAW


def has_raw(session: Session, ticker: str) -> bool:
    """Whether ``eod_raw`` holds any row for the instrument ``ticker`` names."""
    row = session.exec(
        select(col(EodRaw.session_date))
        .where(col(EodRaw.instrument_id) == instrument_of(ticker))
        .limit(1)
    ).first()
    return row is not None


def _rank(series: str) -> int:
    try:
        return RAW_SERIES_ORDER.index(series)
    except ValueError:
        return len(RAW_SERIES_ORDER)


def load_raw_daily(
    session: Session,
    ticker: str,
    *,
    from_: date | None = None,
    to: date | None = None,
    sessions: int | None = None,
) -> list[RawBar]:
    """Raw daily bars of ``ticker`` between ``from_`` and ``to``, oldest first.

    ``sessions`` keeps the newest that many sessions. Series are collapsed to
    one bar per session by :data:`RAW_SERIES_ORDER`.
    """
    stmt = select(EodRaw).where(col(EodRaw.instrument_id) == instrument_of(ticker))
    if from_ is not None:
        stmt = stmt.where(col(EodRaw.session_date) >= from_)
    if to is not None:
        stmt = stmt.where(col(EodRaw.session_date) <= to)
    stmt = stmt.order_by(col(EodRaw.session_date).desc())
    if sessions is not None:
        # At most one row per loaded series per session.
        stmt = stmt.limit(sessions * len(RAW_SERIES_ORDER))
    chosen: dict[date, EodRaw] = {}
    for row in session.exec(stmt).all():
        best = chosen.get(row.session_date)
        if best is None or (_rank(row.series), row.series) < (_rank(best.series), best.series):
            chosen[row.session_date] = row
    days = sorted(chosen)
    if sessions is not None:
        days = days[-sessions:]
    return [
        RawBar(
            ts=datetime.combine(day, time.min),
            open=chosen[day].open,
            high=chosen[day].high,
            low=chosen[day].low,
            close=chosen[day].close,
            volume=int(chosen[day].volume),
            source=chosen[day].source,
            series=chosen[day].series,
        )
        for day in days
    ]


def load_raw_resampled(
    session: Session,
    ticker: str,
    interval: str,
    *,
    bars_wanted: int,
    to: date | None,
    now: datetime | None = None,
) -> list[ResampledBar]:
    """Raw weekly or monthly bars, built like ``load_resampled`` builds the
    adjusted ones: enough sessions for ``bars_wanted`` whole periods, the
    oldest (possibly cut) period dropped when the cap was reached."""
    cap = (bars_wanted + 1) * MAX_SESSIONS_PER_PERIOD[interval]
    end = period_end(to, interval) if to is not None else None
    daily = load_raw_daily(session, ticker, to=end, sessions=cap)
    # The same clock the adjusted path reads (tests patch ``bars.load.now_utc``).
    from stockviz.services.bars import load as bars_load

    clock = now or bars_load.now_utc()
    bars = resample(daily, interval, venue=venue_for_ticker(ticker), now=clock)
    if len(daily) == cap and bars:
        bars = bars[1:]
    return bars


__all__ = [
    "RAW",
    "RAW_SERIES_ORDER",
    "RawBar",
    "has_raw",
    "load_raw_daily",
    "load_raw_resampled",
]
