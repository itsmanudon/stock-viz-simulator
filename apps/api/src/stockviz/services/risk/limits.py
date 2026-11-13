"""Pre-trade limits (Phase 8.5): what a buy would do to the account's caps.

Run under the portfolio lock by ``apply_fill`` (market orders and pending
settlement) and by option opens, and read-only by the order review's
preview. Figures are percentages of NAV in the base currency, as the account
stands before the fill:

- **position:** the holding's value after the fill;
- **order:** the fill's cost;
- **sector:** the sector's stock value after the fill;
- **currency:** a non-base currency's stocks and cash after the fill (a buy
  paid from that currency's own cash moves nothing);
- **VaR:** 1-day 95% historical VaR with the order added to today's
  holdings, an estimate that needs 250 sessions of history.

Sells are never checked: reducing a breach is always allowed.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from decimal import Decimal

from sqlmodel import Session, col, select

from stockviz._time import utcnow
from stockviz.models import Portfolio, RiskLimit, Symbol
from stockviz.services.trading.execute import TradeExecutionError
from stockviz.services.trading.portfolio import (
    PortfolioPosition,
    PortfolioValuation,
    compute_portfolio,
)

LABELS = {
    "max_position_pct": "position",
    "max_order_pct": "single order",
    "max_sector_pct": "sector",
    "max_currency_pct": "currency",
    "max_var_pct": "1-day 95% VaR",
}


class LimitBreached(TradeExecutionError):
    """A buy would take the account past one of its own limits."""


@dataclass(frozen=True, slots=True)
class LimitCheck:
    limit: str
    label: str
    cap: float
    value_after: float | None
    breached: bool
    note: str | None = None


def limits_for(session: Session, portfolio: Portfolio) -> RiskLimit | None:
    row = session.get(RiskLimit, portfolio.id)
    if row is None or all(getattr(row, name) is None for name in LABELS):
        return None
    return row


def _with_order(
    valuation: PortfolioValuation, ticker: str, currency: str, quantity: Decimal, price: Decimal
) -> PortfolioValuation:
    positions = list(valuation.positions)
    for i, p in enumerate(positions):
        if p.ticker == ticker:
            qty = p.quantity + quantity
            positions[i] = dataclasses.replace(
                p, quantity=qty, market_value_native=qty * (p.last_close or price)
            )
            break
    else:
        native = quantity * price
        positions.append(
            PortfolioPosition(
                ticker=ticker, name=ticker, quantity=quantity, currency=currency,
                avg_cost=price, last_close=price, market_value_native=native,
                unrealized_pl_native=Decimal(0), market_value=native, unrealized_pl=Decimal(0),
            )
        )  # fmt: skip
    return dataclasses.replace(valuation, positions=positions)


def _var_after(
    session: Session,
    portfolio: Portfolio,
    valuation: PortfolioValuation,
    *,
    ticker: str,
    currency: str,
    quantity: Decimal,
    price: Decimal,
) -> tuple[float | None, str | None]:
    from stockviz.services.risk.engine import historical_var
    from stockviz.services.risk.scenarios import build_scenarios

    after = _with_order(valuation, ticker, currency, quantity, price)
    scenarios = build_scenarios(session, portfolio, after, horizons=(1,), as_of=utcnow().date())
    if scenarios.reason is not None or 1 not in scenarios.pnl or scenarios.nav_base <= 0:
        return None, f"not checked: {scenarios.reason or 'no history'}"
    result = historical_var(list(scenarios.pnl[1]), confidence=0.95, horizon_days=1)
    if result is None:
        return None, "not checked: no scenarios"
    return result.var / scenarios.nav_base * 100, "estimate: the order added to today's holdings"


def check_buy(
    session: Session,
    portfolio: Portfolio,
    *,
    ticker: str,
    currency: str,
    quantity: Decimal,
    price: Decimal,
    base_cost: Decimal,
    base_debit: Decimal,
    limits: RiskLimit | None = None,
) -> list[LimitCheck]:
    """Every set limit, evaluated as if the buy had filled. Empty when none are set."""
    limits = limits or limits_for(session, portfolio)
    if limits is None:
        return []
    base = portfolio.base_currency or "USD"
    valuation = compute_portfolio(session, portfolio, display_currency=base)
    nav = valuation.total_value
    if nav <= 0:
        return []

    def pct(amount: Decimal) -> float:
        return float(amount / nav * 100)

    held = next((p for p in valuation.positions if p.ticker == ticker), None)
    sectors = dict(
        session.exec(
            select(Symbol.ticker, Symbol.sector).where(
                col(Symbol.ticker).in_([p.ticker for p in valuation.positions] + [ticker])
            )
        ).all()
    )
    values: dict[str, tuple[float | None, str | None]] = {
        "max_order_pct": (pct(base_cost), None),
        "max_position_pct": (pct((held.market_value if held else Decimal(0)) + base_cost), None),
    }
    sector = sectors.get(ticker)
    in_sector = sum(
        (p.market_value for p in valuation.positions if sectors.get(p.ticker) == sector),
        Decimal(0),
    )
    values["max_sector_pct"] = (
        pct(in_sector + base_cost),
        None if sector else "sector not recorded; counted with others not recorded",
    )
    if currency != base:
        stock = sum(
            (p.market_value for p in valuation.positions if p.currency == currency), Decimal(0)
        )
        cash = sum(
            (c.value for c in valuation.cash_by_currency if c.currency == currency), Decimal(0)
        )
        values["max_currency_pct"] = (pct(stock + cash + base_debit), None)
    else:
        values["max_currency_pct"] = (None, f"{base} is the account's own currency")
    if limits.max_var_pct is not None:
        values["max_var_pct"] = _var_after(
            session, portfolio, valuation, ticker=ticker, currency=currency,
            quantity=quantity, price=price,
        )  # fmt: skip

    out: list[LimitCheck] = []
    for name, label in LABELS.items():
        cap = getattr(limits, name)
        if cap is None:
            continue
        value, note = values.get(name, (None, None))
        out.append(
            LimitCheck(
                limit=name,
                label=label,
                cap=float(cap),
                value_after=round(value, 2) if value is not None else None,
                breached=value is not None and value > float(cap),
                note=note,
            )
        )
    return out


def enforce_buy(session: Session, portfolio: Portfolio, **kwargs: object) -> None:
    """Raise :class:`LimitBreached` naming the first limit a buy would cross."""
    limits = limits_for(session, portfolio)
    if limits is None:
        return
    for check in check_buy(session, portfolio, limits=limits, **kwargs):  # type: ignore[arg-type]
        if check.breached:
            raise LimitBreached(
                f"This buy would take your {check.label} to {check.value_after:.2f}% of the "
                f"account, over your limit of {check.cap:.2f}%."
            )


def enforce_option_open(session: Session, portfolio: Portfolio, *, base_debit: Decimal) -> None:
    """An option open is checked against the single-order limit only: its premium
    is not a holding of the underlying, so the other caps do not apply to it."""
    limits = limits_for(session, portfolio)
    if limits is None or limits.max_order_pct is None:
        return
    base = portfolio.base_currency or "USD"
    nav = compute_portfolio(session, portfolio, display_currency=base).total_value
    if nav <= 0:
        return
    value = float(base_debit / nav * 100)
    if value > float(limits.max_order_pct):
        raise LimitBreached(
            f"This option's premium is {value:.2f}% of the account, over your single-order "
            f"limit of {float(limits.max_order_pct):.2f}%."
        )
