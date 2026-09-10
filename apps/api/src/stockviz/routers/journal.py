"""`/v1/portfolio/journal` — realized-P&L calendar for the Track stage.

Two reads, split so the calendar stays cheap: a month carries per-day and
per-week roll-ups but **no** trade list, and a day carries its executions.
Both resolve the caller's own portfolio through ``UserIdDep``; neither accepts
a portfolio or user id from the client.

Accounting semantics — what counts as a trade, how realized P&L is derived,
and how a fill is attributed to a trading session — are documented in
``docs/TRADING_JOURNAL.md``.
"""

from __future__ import annotations

from datetime import UTC
from datetime import date as date_type
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlmodel import Session

from stockviz.auth import UserIdDep
from stockviz.db import get_session
from stockviz.schemas import (
    JournalDayOut,
    JournalDaySummaryOut,
    JournalExecutionOut,
    JournalMonthOut,
    JournalPeriodOut,
    JournalSignalOut,
    JournalStatsOut,
    JournalWeekOut,
    JournalWeekSummaryOut,
)
from stockviz.services.journal import (
    JournalExecution,
    JournalStats,
    day_view,
    month_bounds,
    month_view,
    week_view,
)

router = APIRouter(prefix="/v1/portfolio/journal", tags=["journal"])

SessionDep = Annotated[Session, Depends(get_session)]

JOURNAL_CURRENCY = "USD"
"""Realized P&L is a USD ledger quantity captured at fill-time FX.

Converting history into the user's display currency would re-price past
realizations at today's rate, which is exactly what ``trades.fx_rate`` exists
to prevent. The response labels the currency so the UI never has to assume.
"""

MIN_YEAR = 1970
MAX_YEAR = 2200


def _stats_out(stats: JournalStats) -> JournalStatsOut:
    return JournalStatsOut(
        realized_pnl=stats.realized_pnl,
        trade_count=stats.trade_count,
        winning_trades=stats.winning_trades,
        losing_trades=stats.losing_trades,
        gross_profit=stats.gross_profit,
        gross_loss=stats.gross_loss,
        win_rate=stats.win_rate,
        profit_factor=stats.profit_factor,
    )


def _execution_out(execution: JournalExecution) -> JournalExecutionOut:
    signal = execution.signal_at_entry
    return JournalExecutionOut(
        kind=execution.kind.value,
        reference_id=execution.reference_id,
        ticker=execution.ticker,
        session_date=execution.session_date.isoformat(),
        executed_at=execution.executed_at.replace(tzinfo=UTC),
        realized_pnl=execution.realized_pnl,
        currency=execution.currency,
        side=execution.side,
        quantity=execution.quantity,
        price=execution.price,
        avg_cost=execution.avg_cost,
        option_type=execution.option_type,
        strike=execution.strike,
        expiry=execution.expiry.isoformat() if execution.expiry else None,
        contracts=execution.contracts,
        premium_paid=execution.premium_paid,
        proceeds=execution.proceeds,
        option_status=execution.option_status,
        signal_at_entry=(
            None
            if signal is None
            else JournalSignalOut(
                score=signal.score,
                max_score=signal.max_score,
                computed_at=signal.computed_at,
            )
        ),
    )


@router.get("/months/{year}/{month}", response_model=JournalMonthOut)
def get_journal_month(
    session: SessionDep,
    user_id: UserIdDep,
    year: Annotated[int, Path(ge=MIN_YEAR, le=MAX_YEAR)],
    month: Annotated[int, Path(ge=1, le=12)],
) -> JournalMonthOut:
    """Realized P&L for one New York calendar month, by day and by week.

    ``days`` omits sessions with no closing execution — an inactive month
    returns an empty list rather than 30 zero rows. ``weeks`` always covers
    the whole month so the calendar's summary column lines up with its rows.
    """

    view = month_view(session, user_id=user_id, year=year, month=month)
    first, last = month_bounds(year, month)

    return JournalMonthOut(
        period=JournalPeriodOut(
            year=year,
            month=month,
            first_day=first.isoformat(),
            last_day=last.isoformat(),
        ),
        currency=JOURNAL_CURRENCY,
        summary=_stats_out(view.month.stats),
        return_pct=view.return_pct,
        start_nav=view.start_nav,
        unavailable_count=view.unavailable_count,
        days=[
            JournalDaySummaryOut(date=day.date.isoformat(), stats=_stats_out(day.stats))
            for day in view.month.days
        ],
        weeks=[
            JournalWeekSummaryOut(
                start=week.start.isoformat(),
                end=week.end.isoformat(),
                stats=_stats_out(week.stats),
            )
            for week in view.month.weeks
        ],
    )


@router.get("/days/{day}", response_model=JournalDayOut)
def get_journal_day(
    session: SessionDep,
    user_id: UserIdDep,
    day: date_type,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> JournalDayOut:
    """Every closing execution attributed to one New York trading session.

    Fetched only when a day is opened, which is what keeps the month response
    independent of how many trades the account has.
    """

    if day.year < MIN_YEAR or day.year > MAX_YEAR:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "date out of range")

    view = day_view(session, user_id=user_id, day=day)
    return JournalDayOut(
        date=view.date.isoformat(),
        currency=JOURNAL_CURRENCY,
        stats=_stats_out(view.stats),
        executions=[_execution_out(item) for item in view.executions[offset : offset + limit]],
        offset=offset,
        has_more=offset + limit < len(view.executions),
        unavailable_count=view.unavailable_count,
    )


@router.get("/weeks/{start}", response_model=JournalWeekOut)
def get_journal_week(session: SessionDep, user_id: UserIdDep, start: date_type) -> JournalWeekOut:
    if not MIN_YEAR <= start.year <= MAX_YEAR or (start.day != 1 and start.weekday() != 0):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Expected a Monday or first day of month"
        )
    view = week_view(session, user_id=user_id, start=start)
    return JournalWeekOut(
        start=view.start.isoformat(),
        end=view.end.isoformat(),
        stats=_stats_out(view.stats),
        best_trade=_execution_out(view.best_trade) if view.best_trade else None,
        worst_trade=_execution_out(view.worst_trade) if view.worst_trade else None,
        unavailable_count=view.unavailable_count,
    )
