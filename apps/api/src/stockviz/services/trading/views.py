"""Request-local response builders shared by portfolio endpoints."""

from __future__ import annotations

import contextlib
from datetime import date
from decimal import Decimal

from sqlmodel import Session, select

from stockviz._time import utcnow
from stockviz.models import Portfolio, PortfolioSnapshot, Symbol
from stockviz.schemas import (
    CurrencyCashOut,
    HoldingReturnOut,
    PeriodReturnOut,
    PortfolioAnalyticsOut,
    PortfolioOptionOut,
    PortfolioOut,
    PortfolioReturnsOut,
    PositionOut,
    SectorAllocationOut,
    TopMoverOut,
    ValuationWarningOut,
    XirrOut,
)
from stockviz.services.trading.analytics import (
    compute_annualised_return_pct,
    compute_max_drawdown_pct,
    compute_sector_allocation,
    compute_sharpe,
    compute_top_movers,
    compute_total_return_pct,
)
from stockviz.services.trading.fx import convert as fx_convert
from stockviz.services.trading.portfolio import PortfolioValuation
from stockviz.services.trading.returns import (
    TWR_BASIS,
    TWR_METHOD,
    XIRR_BASIS,
    XIRR_METHOD,
    Xirr,
    period_returns,
)
from stockviz.services.trading.returns_ledger import account_xirr, holding_returns


def portfolio_response(
    snap: PortfolioValuation, *, base_currency_locked: bool = True
) -> PortfolioOut:
    return PortfolioOut(
        portfolio_id=snap.portfolio_id,
        base_currency=snap.base_currency,
        base_currency_locked=base_currency_locked,
        display_currency=snap.display_currency,
        cash_balance=snap.cash_balance,
        cash_by_currency=[
            CurrencyCashOut(currency=c.currency, amount=c.amount, value=c.value)
            for c in snap.cash_by_currency
        ],
        reserved_cash=snap.reserved_cash,
        available_cash=snap.available_cash,
        market_value=snap.market_value,
        options_market_value=snap.options_market_value,
        total_value=snap.total_value,
        total_cost_basis=snap.total_cost_basis,
        unrealized_pl=snap.unrealized_pl,
        unrealized_pl_equity=snap.unrealized_pl_equity,
        unrealized_pl_options=snap.unrealized_pl_options,
        realized_pl=snap.realized_pl,
        realized_pl_unavailable=snap.realized_pl_unavailable,
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
        valuation_warnings=[
            ValuationWarningOut(code=w.code, subject=w.subject, message=w.message)  # type: ignore[arg-type]
            for w in snap.warnings
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
    # LG-1: the series runs from the fixed opening value, through the nightly
    # snapshots, to the live valuation. The first snapshot cannot stand in for
    # the opening: the nightly job overwrites it if the user traded that day.
    portfolio = session.exec(select(Portfolio).where(Portfolio.user_id == user_id)).first()
    opening = portfolio.opening_nav if portfolio is not None else None
    live = Decimal(valuation.total_value)
    # Opening and snapshots are in the base currency (Phase 4.8); so is live.
    if valuation.display_currency != valuation.base_currency:
        with contextlib.suppress(LookupError):
            live = fx_convert(
                session,
                live,
                from_currency=valuation.display_currency,
                to_currency=valuation.base_currency,
            )
    # No track record before two snapshots: report nothing rather than 0%.
    navs = (
        ([opening] if opening is not None else []) + [s.nav for s in snapshots] + [live]
        if len(snapshots) >= 2
        else []
    )
    started = (
        portfolio.created_at.date()
        if portfolio is not None
        else (snapshots[0].date if snapshots else None)
    )
    history_days = max((utcnow().date() - started).days, 0) if started is not None else 0

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
        # Snapshots only: each is an end-of-day value with a session date.
        sharpe_ratio=compute_sharpe(
            [(s.date, s.nav) for s in snapshots], risk_free_rate=risk_free_rate
        ),
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
        returns=(
            _returns_out(session, portfolio, valuation, snapshots, live=live)
            if portfolio is not None
            else None
        ),
    )


def _xirr_out(result: Xirr) -> XirrOut:
    return XirrOut(
        rate_pct=result.rate_pct,
        first_flow=result.first_flow,
        flows=result.flows,
        reason=result.reason,
    )


def _returns_out(
    session: Session,
    portfolio: Portfolio,
    valuation: PortfolioValuation,
    snapshots: list[PortfolioSnapshot],
    *,
    live: Decimal,
) -> PortfolioReturnsOut:
    """Phase 8.1: TWR by period, the account's and each holding's XIRR, in base."""
    as_of = utcnow().date()
    opened = portfolio.created_at.date()
    points: list[tuple[date, Decimal]] = []
    if portfolio.opening_nav is not None:
        points.append((opened, portfolio.opening_nav))
    points += [(s.date, s.nav) for s in snapshots if s.date >= opened]
    points.append((as_of, live))
    return PortfolioReturnsOut(
        currency=valuation.base_currency,
        twr_method=TWR_METHOD,
        twr_basis=TWR_BASIS,
        periods=[
            PeriodReturnOut(
                period=r.period,
                start_date=r.start_date,
                end_date=r.end_date,
                return_pct=r.return_pct,
                annualised_pct=r.annualised_pct,
                reason=r.reason,
            )
            for r in period_returns(points, as_of=as_of, opened=opened)
        ],
        xirr_method=XIRR_METHOD,
        xirr_basis=XIRR_BASIS,
        account_xirr=_xirr_out(account_xirr(portfolio.opening_nav, opened, live, as_of=as_of)),
        holdings=[
            HoldingReturnOut(ticker=h.ticker, kind=h.kind, xirr=_xirr_out(h.result))
            for h in holding_returns(session, portfolio, valuation, as_of=as_of)
        ],
    )
