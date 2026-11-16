"""Read the ledger into the cash flows behind Phase 8.1's returns.

Every amount is in the account's base currency. Equity fills convert at the
rate stored on the trade (``trades.fx_rate``, base units per native unit),
dividends at their stored ``base_value``, and today's holding at the latest
rate. Option premiums are USD: in a non-USD account they have no fill-time
rate, so options get no money-weighted return there (as in the Journal).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlmodel import Session, col, select

from stockviz.models import (
    OptionsPosition,
    OptionStatus,
    Portfolio,
    PortfolioDividend,
    Trade,
    TradeSide,
)
from stockviz.services.trading.fx import convert as fx_convert
from stockviz.services.trading.portfolio import PortfolioValuation
from stockviz.services.trading.returns import MIN_XIRR_DAYS, Xirr, xirr


@dataclass(frozen=True, slots=True)
class RealizedTotals:
    amount: Decimal
    """Base currency: equity sells plus option closes and expiries."""
    unavailable: int
    """Closes with no stored realization (or USD option closes in a non-USD account)."""


@dataclass(frozen=True, slots=True)
class HoldingReturn:
    ticker: str
    kind: str  # "equity" or "options"
    result: Xirr


def realized_totals(session: Session, portfolio: Portfolio) -> RealizedTotals:
    """Lifetime realized P&L for the account (#68), never estimating a missing one."""
    assert portfolio.id is not None
    base = portfolio.base_currency or "USD"
    total = Decimal(0)
    unavailable = 0
    for realized in session.exec(
        select(col(Trade.realized_pnl)).where(
            Trade.portfolio_id == portfolio.id, Trade.side == TradeSide.SELL
        )
    ).all():
        if realized is None:
            unavailable += 1
        else:
            total += realized
    for realized in session.exec(
        select(col(OptionsPosition.realized_pnl)).where(
            OptionsPosition.portfolio_id == portfolio.id,
            col(OptionsPosition.status) != OptionStatus.OPEN,
        )
    ).all():
        if realized is None or base != "USD":
            unavailable += 1
        else:
            total += realized
    return RealizedTotals(total, unavailable)


def _to_base(session: Session, amount: Decimal, currency: str, base: str) -> Decimal | None:
    if currency == base:
        return amount
    try:
        return fx_convert(session, amount, from_currency=currency, to_currency=base)
    except LookupError:
        return None


def holding_returns(
    session: Session, portfolio: Portfolio, valuation: PortfolioValuation, *, as_of: date
) -> list[HoldingReturn]:
    """Money-weighted return of each current equity holding, and of the options book."""
    assert portfolio.id is not None
    base = portfolio.base_currency or "USD"
    out: list[HoldingReturn] = []
    tickers = [p.ticker for p in valuation.positions]
    trades = (
        session.exec(
            select(Trade)
            .where(Trade.portfolio_id == portfolio.id, col(Trade.ticker).in_(tickers))
            .order_by(col(Trade.ts))
        ).all()
        if tickers
        else []
    )
    dividends = (
        session.exec(
            select(PortfolioDividend).where(
                PortfolioDividend.portfolio_id == portfolio.id,
                col(PortfolioDividend.ticker).in_(tickers),
            )
        ).all()
        if tickers
        else []
    )
    for position in valuation.positions:
        flows: list[tuple[date, Decimal]] = []
        missing_rate = False
        for trade in (t for t in trades if t.ticker == position.ticker):
            rate = trade.fx_rate
            if rate is None:
                if position.currency != base:
                    missing_rate = True
                    break
                rate = Decimal(1)
            amount = trade.quantity * trade.price * rate
            flows.append((trade.ts.date(), -amount if trade.side == TradeSide.BUY else amount))
        flows += [(d.ex_date, d.base_value) for d in dividends if d.ticker == position.ticker]
        today = _to_base(session, position.market_value_native, position.currency, base)
        if missing_rate or today is None:
            reason = "a fill has no stored rate" if missing_rate else "no FX rate for today's value"
            out.append(HoldingReturn(position.ticker, "equity", Xirr(None, None, 0, reason)))
            continue
        flows.append((as_of, today))
        out.append(HoldingReturn(position.ticker, "equity", xirr(flows, as_of=as_of)))

    options = session.exec(
        select(OptionsPosition).where(OptionsPosition.portfolio_id == portfolio.id)
    ).all()
    if options:
        out.append(_options_return(session, list(options), valuation, base=base, as_of=as_of))
    return out


def _options_return(
    session: Session,
    options: list[OptionsPosition],
    valuation: PortfolioValuation,
    *,
    base: str,
    as_of: date,
) -> HoldingReturn:
    if base != "USD":
        return HoldingReturn(
            "OPTIONS", "options", Xirr(None, None, 0, "option premiums are USD; not converted")
        )
    flows: list[tuple[date, Decimal]] = []
    for option in options:
        flows.append((option.opened_at.date(), -option.premium_paid))
        if option.status == OptionStatus.OPEN:
            continue
        if option.proceeds is None or option.settled_at is None:
            return HoldingReturn(
                "OPTIONS",
                "options",
                Xirr(None, None, 0, "a closed contract has no stored proceeds"),
            )
        flows.append((option.settled_at.date(), option.proceeds))
    open_value = Decimal(0)
    for held in valuation.option_positions:
        value = _to_base(session, held.market_value_native, held.currency, base)
        if value is None:
            return HoldingReturn(
                "OPTIONS", "options", Xirr(None, None, 0, "no FX rate for today's value")
            )
        open_value += value
    if open_value:
        flows.append((as_of, open_value))
    if not valuation.option_positions and not any(amount > 0 for _, amount in flows):
        # Every contract closed or expired worthless: the premium is all lost.
        first = min(day for day, _ in flows)
        if (as_of - first).days >= MIN_XIRR_DAYS:
            return HoldingReturn("OPTIONS", "options", Xirr(-100.0, first, len(flows)))
    return HoldingReturn("OPTIONS", "options", xirr(flows, as_of=as_of))


def account_xirr(opening: Decimal | None, opened: date, live_base: Decimal, *, as_of: date) -> Xirr:
    """The account's money-weighted return: opening value out, today's NAV in.

    With no outside flows this equals the annualised NAV return; it is
    computed the same way as a holding's so deposits later only add flows.
    """
    if opening is None or opening <= 0:
        return Xirr(None, None, 0, "no opening value")
    return xirr([(opened, -opening), (as_of, live_base)], as_of=as_of)
