"""Trading Journal — realized-P&L aggregation for the Track stage.

Three layers, deliberately separable:

``model``      the unit of account (one closing execution) and what a "trade" is
``query``      reading realized executions out of the ledger, session-dated
``aggregate``  pure day/week/month folds over those executions

``month_view`` and ``day_view`` below are the only entry points a router needs.
Because they are the single call site for aggregation, a cache would slot in
here without touching the router or the folds (ADR-0004 keeps Redis out for
now — this is one indexed range scan over a single user's own rows).

See ``docs/TRADING_JOURNAL.md``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date as date_type
from datetime import timedelta
from decimal import Decimal

from sqlmodel import Session

from stockviz.services.journal.aggregate import (
    JournalDay,
    JournalMonth,
    JournalStats,
    JournalWeek,
    build_month,
    month_bounds,
    summarize,
    week_spans,
)
from stockviz.services.journal.model import (
    ExecutionKind,
    JournalExecution,
    SignalAtEntry,
)
from stockviz.services.journal.query import (
    month_start_nav,
    realized_executions,
    session_date,
    unavailable_realizations,
    utc_window,
)
from stockviz.services.trading.execute import ensure_default_portfolio

__all__ = [
    "ExecutionKind",
    "JournalDay",
    "JournalDayView",
    "JournalExecution",
    "JournalMonth",
    "JournalMonthView",
    "JournalStats",
    "JournalWeek",
    "SignalAtEntry",
    "build_month",
    "day_view",
    "month_bounds",
    "month_view",
    "session_date",
    "summarize",
    "utc_window",
    "week_spans",
]


@dataclass(frozen=True, slots=True)
class JournalMonthView:
    """A month of realized activity, plus the base its percentage is measured on."""

    month: JournalMonth
    start_nav: Decimal | None
    unavailable_count: int = 0

    @property
    def return_pct(self) -> float | None:
        """Realized P&L as a percentage of NAV at the start of the month.

        Not a time-weighted return, and not P&L over the starting cash — those
        would both misstate an account whose capital has changed. ``None`` when
        no snapshot predates the month, in which case the UI hides the metric.
        """
        if self.start_nav is None or self.start_nav <= 0:
            return None
        return float(self.month.stats.realized_pnl / self.start_nav) * 100.0


@dataclass(frozen=True, slots=True)
class JournalDayView:
    date: date_type
    stats: JournalStats
    executions: list[JournalExecution]
    unavailable_count: int = 0


def month_view(session: Session, *, user_id: int, year: int, month: int) -> JournalMonthView:
    """Aggregate one New York calendar month of the user's realized trading."""

    portfolio = ensure_default_portfolio(session, user_id)
    first, last = month_bounds(year, month)
    executions = realized_executions(
        session, portfolio=portfolio, user_id=user_id, first=first, last=last
    )
    return JournalMonthView(
        month=build_month(year=year, month=month, executions=executions),
        start_nav=month_start_nav(session, user_id=user_id, first=first),
        unavailable_count=unavailable_realizations(
            session, portfolio=portfolio, user_id=user_id, first=first, last=last
        ),
    )


def day_view(session: Session, *, user_id: int, day: date_type) -> JournalDayView:
    """Every closing execution for one New York session, with persisted accounting detail.

    Fetched lazily when a day is opened, so the month payload stays O(days)
    however many trades the user has.
    """

    portfolio = ensure_default_portfolio(session, user_id)
    executions = realized_executions(
        session, portfolio=portfolio, user_id=user_id, first=day, last=day
    )
    return JournalDayView(
        date=day,
        stats=summarize(executions),
        executions=executions,
        unavailable_count=unavailable_realizations(
            session, portfolio=portfolio, user_id=user_id, first=day, last=day
        ),
    )


@dataclass(frozen=True, slots=True)
class JournalWeekView:
    start: date_type
    end: date_type
    stats: JournalStats
    best_trade: JournalExecution | None
    worst_trade: JournalExecution | None
    unavailable_count: int = 0


def week_view(session: Session, *, user_id: int, start: date_type) -> JournalWeekView:
    portfolio = ensure_default_portfolio(session, user_id)
    _, last = month_bounds(start.year, start.month)
    end = min(start + timedelta(days=6 - start.weekday()), last)
    executions = realized_executions(
        session, portfolio=portfolio, user_id=user_id, first=start, last=end
    )
    return JournalWeekView(
        start=start,
        end=end,
        stats=summarize(executions),
        best_trade=max(executions, key=lambda row: row.realized_pnl, default=None),
        worst_trade=min(executions, key=lambda row: row.realized_pnl, default=None),
        unavailable_count=unavailable_realizations(
            session, portfolio=portfolio, user_id=user_id, first=start, last=end
        ),
    )
