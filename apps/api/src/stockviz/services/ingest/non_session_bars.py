"""Daily bars dated on a day their venue did not trade (A0, audit MD-9).

The 36 ``.NS`` listings loaded by ``scripts/seed_bulk_daily.py`` (sources
``bulk_*``) hold bars on Saturdays and Sundays: RELIANCE.NS 877 in production
on 11 Nov 2026. A daily bar on a closed day is not a session, so it skews
charts, returns, backtests and replay.

:func:`find_non_session_bars` lists every daily bar whose date is not a
session of its ticker's venue (``services/markets/calendar.py``), split into
weekend and weekday-holiday bars, and marks each one that only repeats the
previous stored bar's prices (a carried-forward copy rather than a trade).
Special sessions in the calendar (``india_holidays.SPECIAL_SESSIONS``:
Budget days, Diwali Muhurat, live system and DR-site tests) count as
sessions and are never listed. On 25 Nov 2026 every weekend bar in
production fell on one of those 12 dates, so check the report's dates
against the exchange's notices before deleting.

:func:`delete_weekend_bars` removes the weekend ones only, for the tickers
named. Weekday-holiday bars are reported, never deleted here: a holiday
added to the calendar late, or a provider dating a bar oddly, needs a person
to look. Deleting production rows is the owner's call (A0 hygiene).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import delete
from sqlmodel import Session, col, select

from stockviz.models import PriceBar
from stockviz.services.ingest.prices import DAILY_INTERVAL
from stockviz.services.instruments import instrument_of
from stockviz.services.markets.calendar import is_session, venue_for_ticker


@dataclass
class TickerReport:
    ticker: str
    venue: str
    weekend: list[date] = field(default_factory=list)
    holiday: list[date] = field(default_factory=list)
    repeats: int = 0
    """Listed bars whose OHLC equals the previous stored bar's."""
    sources: Counter[str] = field(default_factory=Counter)
    """Source of each listed bar."""

    @property
    def total(self) -> int:
        return len(self.weekend) + len(self.holiday)


def _bars(session: Session, ticker: str) -> list[PriceBar]:
    return list(
        session.exec(
            select(PriceBar)
            .where(
                PriceBar.instrument_id == instrument_of(ticker), PriceBar.interval == DAILY_INTERVAL
            )
            .order_by(col(PriceBar.ts))
        ).all()
    )


def _tickers(session: Session) -> list[str]:
    rows = session.exec(
        select(PriceBar.ticker).where(PriceBar.interval == DAILY_INTERVAL).distinct()
    ).all()
    return sorted(rows)


def find_non_session_bars(session: Session, tickers: list[str] | None = None) -> list[TickerReport]:
    """Per ticker with at least one, the daily bars dated on a closed day."""
    reports: list[TickerReport] = []
    for ticker in tickers or _tickers(session):
        venue = venue_for_ticker(ticker)
        report = TickerReport(ticker=ticker, venue=venue)
        previous: PriceBar | None = None
        for bar in _bars(session, ticker):
            day = bar.ts.date()
            if not is_session(day, venue):
                (report.weekend if day.weekday() >= 5 else report.holiday).append(day)
                report.sources[bar.source or "unknown"] += 1
                if previous is not None and (
                    previous.open,
                    previous.high,
                    previous.low,
                    previous.close,
                ) == (bar.open, bar.high, bar.low, bar.close):
                    report.repeats += 1
            previous = bar
        if report.total:
            reports.append(report)
    return reports


def delete_weekend_bars(session: Session, tickers: list[str]) -> dict[str, int]:
    """Delete the Saturday and Sunday daily bars of ``tickers``; returns counts.

    Flushes but does not commit: the caller commits once, so a run either
    removes every listed bar or none.
    """
    if not tickers:
        raise ValueError("name the tickers to clean; there is no all-tickers delete")
    deleted: dict[str, int] = {}
    for report in find_non_session_bars(session, tickers):
        if not report.weekend:
            continue
        weekend = set(report.weekend)
        stamps = [bar.ts for bar in _bars(session, report.ticker) if bar.ts.date() in weekend]
        session.exec(  # type: ignore[call-overload]
            delete(PriceBar).where(
                col(PriceBar.instrument_id) == instrument_of(report.ticker),
                col(PriceBar.interval) == DAILY_INTERVAL,
                col(PriceBar.ts).in_(stamps),
            )
        )
        deleted[report.ticker] = len(stamps)
    session.flush()
    return deleted
