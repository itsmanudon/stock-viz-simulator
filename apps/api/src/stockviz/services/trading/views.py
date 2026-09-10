"""Request-local response builders shared by portfolio endpoints."""

from __future__ import annotations

from sqlmodel import Session, select

from stockviz.models import PortfolioSnapshot, Symbol
from stockviz.schemas import (
    PortfolioAnalyticsOut,
    PortfolioOptionOut,
    PortfolioOut,
    PositionOut,
    SectorAllocationOut,
    TopMoverOut,
)
from stockviz.services.trading.analytics import (
    compute_annualised_return_pct,
    compute_max_drawdown_pct,
    compute_sector_allocation,
    compute_sharpe,
    compute_top_movers,
    compute_total_return_pct,
)
from stockviz.services.trading.portfolio import PortfolioValuation


def portfolio_response(snap: PortfolioValuation) -> PortfolioOut:
    return PortfolioOut(
        portfolio_id=snap.portfolio_id,
        display_currency=snap.display_currency,
        cash_balance=snap.cash_balance,
        reserved_cash=snap.reserved_cash,
        available_cash=snap.available_cash,
        market_value=snap.market_value,
        options_market_value=snap.options_market_value,
        total_value=snap.total_value,
        total_cost_basis=snap.total_cost_basis,
        unrealized_pl=snap.unrealized_pl,
        positions=[
            PositionOut(
                ticker=p.ticker,
                name=p.name,
                quantity=p.quantity,
                currency=p.currency,
                avg_cost=p.avg_cost,
                last_close=p.last_close,
                market_value_native=p.market_value_native,
                unrealized_pl_native=p.unrealized_pl_native,
                market_value=p.market_value,
                unrealized_pl=p.unrealized_pl,
                reserved_quantity=p.reserved_quantity,
                available_quantity=p.available_quantity,
            )
            for p in snap.positions
        ],
        option_positions=[
            PortfolioOptionOut(
                option_id=o.option_id,
                ticker=o.ticker,
                option_type=o.option_type,  # type: ignore[arg-type]
                strike=o.strike,
                expiry=o.expiry,
                quantity=o.quantity,
                currency=o.currency,
                premium_paid=o.premium_paid,
                market_value_native=o.market_value_native,
                market_value=o.market_value,
                unrealized_pl=o.unrealized_pl,
            )
            for o in snap.option_positions
        ],
    )


def portfolio_analytics_response(
    session: Session,
    user_id: int,
    valuation: PortfolioValuation,
    *,
    risk_free_rate: float,
) -> PortfolioAnalyticsOut:
    snapshots = list(
        session.exec(
            select(PortfolioSnapshot)
            .where(PortfolioSnapshot.user_id == user_id)
            .order_by(PortfolioSnapshot.date.asc())  # type: ignore[attr-defined]
        )
    )
    navs = [s.nav for s in snapshots]
    history_days = (snapshots[-1].date - snapshots[0].date).days or 1 if len(snapshots) >= 2 else 0

    position_tickers = [p.ticker for p in valuation.positions]
    sectors_by_ticker: dict[str, str | None] = (
        dict(
            session.exec(
                select(Symbol.ticker, Symbol.sector).where(
                    Symbol.ticker.in_(position_tickers)  # type: ignore[attr-defined]
                )
            ).all()  # type: ignore[arg-type]
        )
        if position_tickers
        else {}
    )

    allocation = compute_sector_allocation(valuation.positions, sectors_by_ticker=sectors_by_ticker)
    gainers, losers = compute_top_movers(valuation.positions, sectors_by_ticker=sectors_by_ticker)

    return PortfolioAnalyticsOut(
        display_currency=valuation.display_currency,
        history_days=history_days,
        total_return_pct=compute_total_return_pct(navs),
        annualised_return_pct=(
            compute_annualised_return_pct(navs, days=history_days) if history_days else None
        ),
        sharpe_ratio=compute_sharpe(navs, risk_free_rate=risk_free_rate),
        max_drawdown_pct=compute_max_drawdown_pct(navs),
        risk_free_rate=risk_free_rate,
        sector_allocation=[
            SectorAllocationOut(sector=a.sector, market_value=a.market_value, pct=a.pct)
            for a in allocation
        ],
        top_gainers=[
            TopMoverOut(
                ticker=m.ticker,
                name=m.name,
                sector=m.sector,
                unrealized_pl=m.unrealized_pl,
                return_pct=m.return_pct,
            )
            for m in gainers
        ],
        top_losers=[
            TopMoverOut(
                ticker=m.ticker,
                name=m.name,
                sector=m.sector,
                unrealized_pl=m.unrealized_pl,
                return_pct=m.return_pct,
            )
            for m in losers
        ],
    )
