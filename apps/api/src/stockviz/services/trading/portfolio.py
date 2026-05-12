"""Portfolio valuation.

``compute_portfolio`` snapshots a user's default portfolio: positions priced
at the latest close, cash balance as-is, and the aggregates the UI needs
(total value, total cost basis, unrealized P&L).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from sqlmodel import Session, select

from stockviz.models import Portfolio, Position, PriceBar, Symbol


@dataclass(frozen=True, slots=True)
class PortfolioPosition:
    ticker: str
    name: str
    quantity: Decimal
    avg_cost: Decimal
    last_close: Decimal | None
    market_value: Decimal
    unrealized_pl: Decimal


@dataclass(frozen=True, slots=True)
class PortfolioValuation:
    portfolio_id: int
    cash_balance: Decimal
    positions: list[PortfolioPosition] = field(default_factory=list)
    market_value: Decimal = Decimal(0)
    total_value: Decimal = Decimal(0)
    total_cost_basis: Decimal = Decimal(0)
    unrealized_pl: Decimal = Decimal(0)


def _latest_close_map(session: Session, tickers: list[str]) -> dict[str, Decimal]:
    """Per-ticker latest close. Empty dict if ``tickers`` is empty."""
    if not tickers:
        return {}
    out: dict[str, Decimal] = {}
    for ticker in tickers:
        bar = session.exec(
            select(PriceBar)
            .where(PriceBar.ticker == ticker, PriceBar.interval == "1d")
            .order_by(PriceBar.ts.desc())  # type: ignore[attr-defined]
            .limit(1)
        ).first()
        if bar is not None:
            out[ticker] = bar.close
    return out


def compute_portfolio(session: Session, portfolio: Portfolio) -> PortfolioValuation:
    """Snapshot the portfolio with latest-close pricing."""

    assert portfolio.id is not None

    rows = list(
        session.exec(
            select(Position, Symbol)
            .where(Position.portfolio_id == portfolio.id)  # type: ignore[arg-type]
            .join(Symbol, Symbol.ticker == Position.ticker)  # type: ignore[arg-type]
        )
    )
    tickers = [pos.ticker for pos, _ in rows]
    close_by_ticker = _latest_close_map(session, tickers)

    positions: list[PortfolioPosition] = []
    market_value = Decimal(0)
    cost_basis = Decimal(0)
    for pos, sym in rows:
        last = close_by_ticker.get(pos.ticker)
        pos_market_value = (last * pos.quantity) if last is not None else Decimal(0)
        pos_cost = pos.avg_cost * pos.quantity
        positions.append(
            PortfolioPosition(
                ticker=pos.ticker,
                name=sym.name,
                quantity=pos.quantity,
                avg_cost=pos.avg_cost,
                last_close=last,
                market_value=pos_market_value,
                unrealized_pl=pos_market_value - pos_cost,
            )
        )
        market_value += pos_market_value
        cost_basis += pos_cost

    total_value = market_value + portfolio.cash_balance
    return PortfolioValuation(
        portfolio_id=portfolio.id,
        cash_balance=portfolio.cash_balance,
        positions=positions,
        market_value=market_value,
        total_value=total_value,
        total_cost_basis=cost_basis,
        unrealized_pl=market_value - cost_basis,
    )
