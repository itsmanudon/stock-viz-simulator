"""Pure aggregation over realized executions.

Everything in this module is a function of a list of :class:`JournalExecution`
— no database, no HTTP, no clock. That is what makes the month/week/day
arithmetic (scratch trades, empty days, month boundaries, decimal precision)
testable without a fixture, and what would let a cache wrap the whole thing at
one call site later. See ``docs/TRADING_JOURNAL.md``.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date as date_type
from datetime import timedelta
from decimal import Decimal

from stockviz.services.journal.model import JournalExecution

ZERO = Decimal("0")


@dataclass(frozen=True, slots=True)
class JournalStats:
    """Realized-P&L roll-up over any set of closing executions.

    ``trade_count`` counts every closing execution, including scratches
    (exactly zero realized P&L), which are in neither ``winning_trades`` nor
    ``losing_trades``. ``win_rate`` therefore divides by winners + losers, and
    is ``None`` when that is zero rather than reporting a 0% win rate for a day
    that had no decided trades.
    """

    realized_pnl: Decimal = ZERO
    trade_count: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    gross_profit: Decimal = ZERO
    gross_loss: Decimal = ZERO  # positive magnitude of the losing side

    @property
    def win_rate(self) -> float | None:
        decided = self.winning_trades + self.losing_trades
        if decided == 0:
            return None
        return self.winning_trades / decided

    @property
    def profit_factor(self) -> float | None:
        """Gross profit / gross loss. ``None`` when nothing was lost.

        A month with no losing trade has no finite profit factor; reporting a
        huge number or 0 would both be wrong, so the UI hides the metric.
        """
        if self.gross_loss <= ZERO:
            return None
        return float(self.gross_profit / self.gross_loss)


def summarize(executions: Iterable[JournalExecution]) -> JournalStats:
    """Fold closing executions into a :class:`JournalStats`."""

    realized = ZERO
    count = winners = losers = 0
    gross_profit = ZERO
    gross_loss = ZERO

    for execution in executions:
        pnl = execution.realized_pnl
        realized += pnl
        count += 1
        if pnl > ZERO:
            winners += 1
            gross_profit += pnl
        elif pnl < ZERO:
            losers += 1
            gross_loss += -pnl

    return JournalStats(
        realized_pnl=realized,
        trade_count=count,
        winning_trades=winners,
        losing_trades=losers,
        gross_profit=gross_profit,
        gross_loss=gross_loss,
    )


@dataclass(frozen=True, slots=True)
class JournalDay:
    date: date_type
    stats: JournalStats


@dataclass(frozen=True, slots=True)
class JournalWeek:
    """One Monday-anchored week, clipped to the month being viewed.

    ``start``/``end`` are the *visible* bounds — the week containing the 1st
    starts on the 1st, not on the preceding Monday — so the range the inspector
    shows always matches the days the row actually aggregates.
    """

    start: date_type
    end: date_type
    stats: JournalStats


@dataclass(frozen=True, slots=True)
class JournalMonth:
    year: int
    month: int
    stats: JournalStats
    days: list[JournalDay] = field(default_factory=list)
    weeks: list[JournalWeek] = field(default_factory=list)


def group_by_day(executions: Iterable[JournalExecution]) -> dict[date_type, list[JournalExecution]]:
    buckets: dict[date_type, list[JournalExecution]] = defaultdict(list)
    for execution in executions:
        buckets[execution.session_date].append(execution)
    return dict(buckets)


def month_bounds(year: int, month: int) -> tuple[date_type, date_type]:
    """First and last calendar day of ``year``-``month`` (inclusive)."""

    first = date_type(year, month, 1)
    next_month = date_type(year + 1, 1, 1) if month == 12 else date_type(year, month + 1, 1)
    return first, next_month - timedelta(days=1)


def week_spans(first: date_type, last: date_type) -> list[tuple[date_type, date_type]]:
    """Monday-anchored week spans covering ``first``..``last``, clipped to it."""

    spans: list[tuple[date_type, date_type]] = []
    cursor = first
    while cursor <= last:
        # weekday(): Monday == 0. Sunday closes the week.
        week_end = min(cursor + timedelta(days=6 - cursor.weekday()), last)
        spans.append((cursor, week_end))
        cursor = week_end + timedelta(days=1)
    return spans


def build_month(*, year: int, month: int, executions: Sequence[JournalExecution]) -> JournalMonth:
    """Aggregate ``executions`` into day buckets, week buckets, and a total.

    Only days that actually had a closing execution appear in ``days`` — an
    empty month returns an empty list, and the calendar grid renders quiet
    cells for the rest. Every week in the month appears in ``weeks``, including
    silent ones, so the calendar's right-hand column always lines up with its
    rows.
    """

    by_day = group_by_day(executions)
    first, last = month_bounds(year, month)

    days = [
        JournalDay(date=day, stats=summarize(by_day[day]))
        for day in sorted(by_day)
        if first <= day <= last
    ]

    weeks = [
        JournalWeek(
            start=start,
            end=end,
            stats=summarize(
                item for day, items in by_day.items() if start <= day <= end for item in items
            ),
        )
        for start, end in week_spans(first, last)
    ]

    in_month = [item for item in executions if first <= item.session_date <= last]
    return JournalMonth(
        year=year,
        month=month,
        stats=summarize(in_month),
        days=days,
        weeks=weeks,
    )
