"""Reading realized executions out of the ledger.

The Journal never invents a number. Equity realizations come from
``trades.realized_pnl`` (written by ``apply_fill``) and option realizations
from ``options_positions.realized_pnl`` (written when a contract leaves
``OPEN``). Rows without a persisted realization are skipped, not estimated.

Every query here is scoped to one user's own portfolio; no caller-supplied
portfolio or user id is ever accepted.
"""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from datetime import date as date_type
from decimal import Decimal

from sqlalchemy import func, or_
from sqlmodel import Session, col, select

from stockviz.models import (
    OptionsPosition,
    OptionStatus,
    Portfolio,
    PortfolioSnapshot,
    Symbol,
    Trade,
    TradeSide,
)
from stockviz.services.ingest.bar_semantics import NEW_YORK, new_york_session_date
from stockviz.services.journal.model import (
    ExecutionKind,
    JournalExecution,
)


def session_date(ts: datetime) -> date_type:
    """New York trading-session date for a naive-UTC ledger timestamp.

    Timestamps are stored naive UTC (see ``stockviz._time``), so they are
    re-attached to UTC before conversion. A fill at 2026-08-20T01:30Z belongs
    to the **Aug 19** session; ``zoneinfo`` handles DST, so no fixed offset is
    assumed anywhere.
    """

    aware = ts.replace(tzinfo=UTC) if ts.tzinfo is None else ts
    return new_york_session_date(aware)


def utc_window(first: date_type, last: date_type) -> tuple[datetime, datetime]:
    """Half-open naive-UTC range covering New York sessions ``first``..``last``.

    Converting the *bounds* rather than the column keeps the predicate
    index-friendly (``ts >= ? AND ts < ?`` uses ``ix_trades_portfolio_ts``);
    wrapping ``ts`` in a timezone function would force a scan. The window is
    built from real New York midnights, so it is one hour wider or narrower
    across a DST boundary — exactly as it should be.
    """

    start = datetime.combine(first, time.min, tzinfo=NEW_YORK)
    end = datetime.combine(last + timedelta(days=1), time.min, tzinfo=NEW_YORK)
    return (
        start.astimezone(UTC).replace(tzinfo=None),
        end.astimezone(UTC).replace(tzinfo=None),
    )


def _equity_executions(
    session: Session, *, portfolio_id: int, start: datetime, end: datetime
) -> list[JournalExecution]:
    rows = list(
        session.exec(
            select(Trade)
            .where(
                Trade.portfolio_id == portfolio_id,
                Trade.ts >= start,
                Trade.ts < end,
                Trade.realized_pnl.is_not(None),  # type: ignore[union-attr]
            )
            .order_by(Trade.ts.asc(), Trade.id.asc())  # type: ignore[attr-defined]
        )
    )
    if not rows:
        return []

    currency_by_ticker = _currencies(session, {row.ticker for row in rows})
    return [
        JournalExecution(
            kind=ExecutionKind.EQUITY,
            reference_id=row.id or 0,
            ticker=row.ticker,
            session_date=session_date(row.ts),
            executed_at=row.ts,
            realized_pnl=row.realized_pnl or Decimal("0"),
            side=row.side.value,
            quantity=row.quantity,
            price=row.price,
            avg_cost=row.avg_cost_at_fill,
            currency=currency_by_ticker.get(row.ticker, "USD"),
        )
        for row in rows
    ]


def _option_executions(
    session: Session, *, user_id: int, portfolio_id: int, start: datetime, end: datetime
) -> list[JournalExecution]:
    rows = list(
        session.exec(
            select(OptionsPosition)
            .join(Symbol, col(Symbol.ticker) == col(OptionsPosition.ticker))
            .where(
                Symbol.currency == "USD",
                OptionsPosition.user_id == user_id,
                OptionsPosition.portfolio_id == portfolio_id,
                OptionsPosition.status != OptionStatus.OPEN,
                OptionsPosition.settled_at.is_not(None),  # type: ignore[union-attr]
                OptionsPosition.settled_at >= start,  # type: ignore[operator]
                OptionsPosition.settled_at < end,  # type: ignore[operator]
                OptionsPosition.realized_pnl.is_not(None),  # type: ignore[union-attr]
            )
            .order_by(OptionsPosition.settled_at.asc())  # type: ignore[attr-defined]
        )
    )
    if not rows:
        return []

    currency_by_ticker = _currencies(session, {row.ticker for row in rows})
    executions: list[JournalExecution] = []
    for row in rows:
        assert row.settled_at is not None
        executions.append(
            JournalExecution(
                kind=ExecutionKind.OPTION,
                reference_id=row.id or 0,
                ticker=row.ticker,
                session_date=session_date(row.settled_at),
                executed_at=row.settled_at,
                realized_pnl=row.realized_pnl or Decimal("0"),
                currency=currency_by_ticker.get(row.ticker, "USD"),
                option_type=row.option_type.value,
                strike=row.strike,
                expiry=row.expiry,
                contracts=row.quantity,
                premium_paid=row.premium_paid,
                proceeds=row.proceeds,
                option_status=row.status.value,
            )
        )
    return executions


def _currencies(session: Session, tickers: set[str]) -> dict[str, str]:
    """One query for the page's symbols instead of one per execution."""

    if not tickers:
        return {}
    return {
        ticker: (currency or "USD")
        for ticker, currency in session.exec(
            select(Symbol.ticker, Symbol.currency).where(Symbol.ticker.in_(tickers))  # type: ignore[attr-defined]
        ).all()
    }


def realized_executions(
    session: Session,
    *,
    portfolio: Portfolio,
    user_id: int,
    first: date_type,
    last: date_type,
) -> list[JournalExecution]:
    """Every closing execution attributed to sessions ``first``..``last``.

    Equity and option legs are merged and sorted by execution time. Both are
    read with a half-open UTC window, then re-attributed to New York session
    dates; because the window is built from New York midnights, no execution is
    ever pulled in or dropped by the conversion.
    """

    assert portfolio.id is not None
    start, end = utc_window(first, last)
    executions = _equity_executions(
        session, portfolio_id=portfolio.id, start=start, end=end
    ) + _option_executions(
        session, user_id=user_id, portfolio_id=portfolio.id, start=start, end=end
    )
    executions.sort(key=lambda item: (item.executed_at, item.reference_id))
    return executions


def month_start_nav(session: Session, *, user_id: int, first: date_type) -> Decimal | None:
    """Portfolio NAV on the last snapshot strictly before the month.

    The denominator for the month's percentage figure. ``None`` when the
    account has no snapshot yet — the UI hides the metric rather than dividing
    by the starting cash, which stops being the right base as soon as the
    account's capital changes.
    """

    row = session.exec(
        select(PortfolioSnapshot)
        .where(PortfolioSnapshot.user_id == user_id, PortfolioSnapshot.date < first)
        .order_by(PortfolioSnapshot.date.desc())  # type: ignore[attr-defined]
        .limit(1)
    ).first()
    if row is None or row.nav <= 0:
        return None
    return row.nav


def unavailable_realizations(
    session: Session, *, portfolio: Portfolio, user_id: int, first: date_type, last: date_type
) -> int:
    """Count dated closes lacking reliable USD accounting; never silently call them zero."""
    start, end = utc_window(first, last)
    equity = session.exec(
        select(func.count())
        .select_from(Trade)
        .where(
            Trade.portfolio_id == portfolio.id,
            Trade.side == TradeSide.SELL,
            Trade.ts >= start,
            Trade.ts < end,
            col(Trade.realized_pnl).is_(None),
        )
    ).one()
    options = session.exec(
        select(func.count())
        .select_from(OptionsPosition)
        .join(Symbol, col(Symbol.ticker) == col(OptionsPosition.ticker))
        .where(
            OptionsPosition.user_id == user_id,
            OptionsPosition.portfolio_id == portfolio.id,
            OptionsPosition.status != OptionStatus.OPEN,
            col(OptionsPosition.settled_at) >= start,
            col(OptionsPosition.settled_at) < end,
            or_(col(OptionsPosition.realized_pnl).is_(None), col(Symbol.currency) != "USD"),
        )
    ).one()
    return equity + options
