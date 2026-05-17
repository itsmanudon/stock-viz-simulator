"""Portfolio valuation.

``compute_portfolio`` snapshots a user's default portfolio: positions priced
at the latest close in their native currency, then converted into a chosen
display currency. Cash is held in USD; ``cash_balance`` on the returned
valuation is already in the display currency.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from sqlmodel import Session, select

from stockviz.models import Portfolio, Position, PriceBar, Symbol
from stockviz.services.trading.fx import convert as fx_convert
from stockviz.services.trading.fx import latest_rate


@dataclass(frozen=True, slots=True)
class PortfolioPosition:
    ticker: str
    name: str
    quantity: Decimal
    # Native currency the symbol trades in (e.g. EUR for SAP.DE).
    currency: str
    # Per-share cost basis in native currency.
    avg_cost: Decimal
    # Latest close in native currency. None when there's no bar yet.
    last_close: Decimal | None
    # Holding's market value in native currency.
    market_value_native: Decimal
    # Unrealized P&L in native currency.
    unrealized_pl_native: Decimal
    # Same numbers converted to the user's display currency.
    market_value: Decimal
    unrealized_pl: Decimal


@dataclass(frozen=True, slots=True)
class PortfolioValuation:
    portfolio_id: int
    # Currency every aggregate (cash, market_value, totals) is denominated in.
    display_currency: str
    cash_balance: Decimal
    positions: list[PortfolioPosition] = field(default_factory=list)
    market_value: Decimal = Decimal(0)
    total_value: Decimal = Decimal(0)
    total_cost_basis: Decimal = Decimal(0)
    unrealized_pl: Decimal = Decimal(0)


def _latest_close_map(session: Session, tickers: list[str]) -> dict[str, Decimal]:
    """Per-ticker latest close (in the symbol's native currency)."""
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


def compute_portfolio(
    session: Session,
    portfolio: Portfolio,
    *,
    display_currency: str = "USD",
) -> PortfolioValuation:
    """Snapshot the portfolio with latest-close pricing in ``display_currency``.

    The cash balance is stored in USD; we convert it to the display currency
    before returning. Per-position values are exposed in both native and
    display currency so the UI can show either side.

    Missing FX rates are treated as "skip conversion" for that one position
    (the native amount is used as-is) — a defensive choice so the page still
    renders if the FX refresh is briefly behind.
    """

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

    def _to_display(amount: Decimal, from_ccy: str) -> Decimal:
        if from_ccy == display_currency:
            return amount
        try:
            return fx_convert(session, amount, from_currency=from_ccy, to_currency=display_currency)
        except LookupError:
            return amount

    positions: list[PortfolioPosition] = []
    market_value_display = Decimal(0)
    cost_basis_display = Decimal(0)
    for pos, sym in rows:
        native_ccy = sym.currency or "USD"
        last = close_by_ticker.get(pos.ticker)
        mv_native = (last * pos.quantity) if last is not None else Decimal(0)
        cost_native = pos.avg_cost * pos.quantity
        pl_native = mv_native - cost_native

        mv_display = _to_display(mv_native, native_ccy)
        cost_display = _to_display(cost_native, native_ccy)
        pl_display = mv_display - cost_display

        positions.append(
            PortfolioPosition(
                ticker=pos.ticker,
                name=sym.name,
                quantity=pos.quantity,
                currency=native_ccy,
                avg_cost=pos.avg_cost,
                last_close=last,
                market_value_native=mv_native,
                unrealized_pl_native=pl_native,
                market_value=mv_display,
                unrealized_pl=pl_display,
            )
        )
        market_value_display += mv_display
        cost_basis_display += cost_display

    # Cash is USD-base — convert to display currency.
    if display_currency == "USD":
        cash_display = portfolio.cash_balance
    else:
        try:
            usd_per_display = latest_rate(session, display_currency)
            cash_display = (
                portfolio.cash_balance / usd_per_display
                if usd_per_display != Decimal(0)
                else portfolio.cash_balance
            )
        except LookupError:
            cash_display = portfolio.cash_balance

    total_value = market_value_display + cash_display
    return PortfolioValuation(
        portfolio_id=portfolio.id,
        display_currency=display_currency,
        cash_balance=cash_display,
        positions=positions,
        market_value=market_value_display,
        total_value=total_value,
        total_cost_basis=cost_basis_display,
        unrealized_pl=market_value_display - cost_basis_display,
    )
