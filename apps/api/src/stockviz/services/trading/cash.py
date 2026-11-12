"""Cash per currency (Phase 4.5b, design note option B).

A portfolio holds cash in its base currency (``portfolios.cash_balance``,
USD) and in any other currency it has sold into (``cash_balances``). An
equity fill in a currency other than the base:

- **buy**: spends that currency's balance first; any shortfall is converted
  from the base at the fill's rate and recorded in ``fx_conversions``;
- **sell**: credits that currency's balance. Nothing converts back on its own.

Option premiums and dividends stay in the base currency for now (options are
USD-only until Phase 9; dividends convert at the ex-date rate as before).
Every function stages changes and does not commit; callers hold the portfolio
row lock (``apply_fill``), so balances cannot race.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date as date_type
from decimal import Decimal

from sqlmodel import Session, col, select

from stockviz.models import CashBalance, FxConversion, FxRate, Portfolio

MICROS = Decimal("0.000001")


def base_currency(portfolio: Portfolio) -> str:
    return portfolio.base_currency or "USD"


def _row(session: Session, portfolio_id: int, currency: str) -> CashBalance | None:
    return session.exec(
        select(CashBalance).where(
            col(CashBalance.portfolio_id) == portfolio_id,
            col(CashBalance.currency) == currency,
        )
    ).first()


def balance(session: Session, portfolio: Portfolio, currency: str) -> Decimal:
    """Cash held in ``currency`` (the base balance for the base currency)."""
    if currency == base_currency(portfolio):
        return portfolio.cash_balance
    assert portfolio.id is not None
    row = _row(session, portfolio.id, currency)
    return row.amount if row is not None else Decimal(0)


def balances(session: Session, portfolio: Portfolio) -> dict[str, Decimal]:
    """Every non-zero cash balance, base currency first."""
    assert portfolio.id is not None
    out = {base_currency(portfolio): portfolio.cash_balance}
    for row in session.exec(
        select(CashBalance)
        .where(col(CashBalance.portfolio_id) == portfolio.id, col(CashBalance.amount) > 0)
        .order_by(col(CashBalance.currency))
    ).all():
        out[row.currency] = row.amount
    return out


def credit(session: Session, portfolio: Portfolio, currency: str, amount: Decimal) -> None:
    if amount == 0:
        return
    if currency == base_currency(portfolio):
        portfolio.cash_balance = (portfolio.cash_balance + amount).quantize(MICROS)
        session.add(portfolio)
        return
    assert portfolio.id is not None
    row = _row(session, portfolio.id, currency)
    if row is None:
        row = CashBalance(portfolio_id=portfolio.id, currency=currency, amount=Decimal(0))
    row.amount = (row.amount + amount).quantize(MICROS)
    session.add(row)


@dataclass(frozen=True, slots=True)
class BuyFunding:
    """How a buy of ``native_cost`` in ``currency`` is paid for."""

    from_balance: Decimal  # spent from the currency's own balance
    shortfall: Decimal  # converted from the base currency
    base_debit: Decimal  # shortfall * rate, in the base currency


def plan_buy(
    session: Session, portfolio: Portfolio, currency: str, native_cost: Decimal, rate: Decimal
) -> BuyFunding:
    """Split a buy between the currency's balance and a conversion from base."""
    if currency == base_currency(portfolio):
        return BuyFunding(Decimal(0), native_cost, native_cost)
    held = balance(session, portfolio, currency)
    from_balance = min(held, native_cost)
    shortfall = native_cost - from_balance
    return BuyFunding(from_balance, shortfall, (shortfall * rate).quantize(MICROS))


def _rate_date(session: Session, currency: str) -> date_type | None:
    return session.exec(
        select(col(FxRate.date))
        .where(col(FxRate.currency) == currency)
        .order_by(col(FxRate.date).desc())
        .limit(1)
    ).first()


def pay_for_buy(
    session: Session,
    portfolio: Portfolio,
    currency: str,
    funding: BuyFunding,
    rate: Decimal,
) -> FxConversion | None:
    """Apply ``funding``. Returns the conversion row, if one was needed.

    The caller has already checked the base balance covers ``base_debit``.
    """
    base = base_currency(portfolio)
    portfolio.cash_balance = (portfolio.cash_balance - funding.base_debit).quantize(MICROS)
    session.add(portfolio)
    if currency == base:
        return None
    assert portfolio.id is not None
    if funding.from_balance > 0:
        row = _row(session, portfolio.id, currency)
        assert row is not None
        row.amount = (row.amount - funding.from_balance).quantize(MICROS)
        session.add(row)
    if funding.shortfall <= 0:
        return None
    conversion = FxConversion(
        portfolio_id=portfolio.id,
        from_currency=base,
        to_currency=currency,
        from_amount=funding.base_debit,
        to_amount=funding.shortfall.quantize(MICROS),
        rate=rate,
        rate_date=_rate_date(session, currency),
        reason="buy",
    )
    session.add(conversion)
    return conversion
