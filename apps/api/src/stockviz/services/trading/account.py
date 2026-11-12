"""The account's base currency (Phase 4.8: rupee portfolios).

A paper account keeps its cash in one base currency, USD or INR. The owner's
rule (13 Nov 2026): a user may switch it only while the account is fresh —
no trades, orders, options, dividends or foreign cash — so nothing already
booked changes meaning. Switching restarts the account at that currency's
starting cash: $100,000 or ₹1 crore.
"""

from __future__ import annotations

from decimal import Decimal

from sqlmodel import Session, col, select

from stockviz.models import (
    CashBalance,
    OptionsPosition,
    PendingOrder,
    Portfolio,
    PortfolioDividend,
    PortfolioSnapshot,
    Position,
    Trade,
    User,
)

STARTING_CASH: dict[str, Decimal] = {
    "USD": Decimal("100000.00"),
    "INR": Decimal("10000000.00"),  # ₹1 crore
}


class UnsupportedBaseCurrency(ValueError):
    """Only the currencies in ``STARTING_CASH`` can be a base."""


class AccountNotFresh(Exception):
    """The account has activity, so its base currency is fixed."""


def activity(session: Session, portfolio: Portfolio) -> list[str]:
    """What the account has done, in words; empty when it is fresh."""
    assert portfolio.id is not None
    pid = portfolio.id
    checks: list[tuple[str, object]] = [
        ("trades", select(Trade.id).where(Trade.portfolio_id == pid)),
        ("orders", select(PendingOrder.id).where(PendingOrder.portfolio_id == pid)),
        ("options", select(OptionsPosition.id).where(OptionsPosition.portfolio_id == pid)),
        ("positions", select(Position.id).where(Position.portfolio_id == pid)),
        ("dividends", select(PortfolioDividend.id).where(PortfolioDividend.portfolio_id == pid)),
        (
            "foreign cash",
            select(CashBalance.id).where(
                CashBalance.portfolio_id == pid, col(CashBalance.amount) != 0
            ),
        ),
    ]
    return [name for name, stmt in checks if session.exec(stmt.limit(1)).first() is not None]  # type: ignore[attr-defined]


def set_base_currency(session: Session, *, user_id: int, currency: str) -> Portfolio:
    """Restart a fresh account in ``currency``. Commits.

    A repeat with the account's current currency changes nothing. Raises
    :class:`UnsupportedBaseCurrency` or :class:`AccountNotFresh`.
    """
    from stockviz.services.trading.buying_power import lock_portfolio
    from stockviz.services.trading.execute import ensure_default_portfolio

    currency = currency.upper()
    if currency not in STARTING_CASH:
        raise UnsupportedBaseCurrency(
            f"Base currency must be one of {', '.join(sorted(STARTING_CASH))}"
        )
    portfolio = ensure_default_portfolio(session, user_id)
    assert portfolio.id is not None
    portfolio = lock_portfolio(session, portfolio.id)
    if (portfolio.base_currency or "USD") == currency:
        session.rollback()
        return portfolio
    done = activity(session, portfolio)
    if done:
        session.rollback()
        raise AccountNotFresh(
            "The base currency can only change before the account's first trade, "
            f"order or option; this account has {', '.join(done)}."
        )

    start = STARTING_CASH[currency]
    portfolio.base_currency = currency
    portfolio.cash_balance = start
    portfolio.opening_nav = start
    session.add(portfolio)
    # A fresh account's snapshots are its starting cash; restate them in the
    # new currency so the equity curve and returns start from the new opening.
    for snap in session.exec(
        select(PortfolioSnapshot).where(PortfolioSnapshot.user_id == user_id)
    ).all():
        snap.nav = start
        session.add(snap)
    user = session.get(User, user_id)
    if user is not None:
        # Show the account in its own currency; Settings can still change it.
        user.display_currency = currency
        session.add(user)
    session.commit()
    session.refresh(portfolio)
    return portfolio
