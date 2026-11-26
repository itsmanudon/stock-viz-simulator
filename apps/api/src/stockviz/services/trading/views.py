"""Request-local response builders shared by portfolio endpoints."""

from __future__ import annotations

import contextlib
from datetime import date
from decimal import Decimal

from sqlmodel import Session, select

from stockviz._time import utcnow
from stockviz.models import Portfolio, PortfolioSnapshot, Symbol
from stockviz.schemas import (
    CombinedBookOut,
    CombinedOut,
    CurrencyCashOut,
    ExposureBucketOut,
    ExposureOut,
    HoldingAttributionOut,
    HoldingReturnOut,
    OptionGreeksOut,
    PeriodReturnOut,
    PortfolioAnalyticsOut,
    PortfolioAttributionOut,
    PortfolioExposureOut,
    PortfolioOptionOut,
    PortfolioOut,
    PortfolioReturnsOut,
    PositionOut,
    SectorAllocationOut,
    TopMoverOut,
    ValuationWarningOut,
    XirrOut,
)
from stockviz.services.books.combined import (
    COMBINED_TWR_BASIS,
    COMBINED_XIRR_BASIS,
    FX_STALE_RULE,
    CombinedView,
    combined_xirr_flows,
    growth_index,
)
from stockviz.services.options.pricing import OptionPrice
from stockviz.services.trading.analytics import (
    compute_annualised_return_pct,
    compute_max_drawdown_pct,
    compute_sector_allocation,
    compute_sharpe,
    compute_top_movers,
    compute_total_return_pct,
)
from stockviz.services.trading.attribution import ATTRIBUTION_BASIS, ATTRIBUTION_METHOD, attribute
from stockviz.services.trading.exposure import (
    EXPOSURE_BASIS,
    EXPOSURE_METHOD,
    classifications,
    compute_exposure,
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
    xirr,
)
from stockviz.services.trading.returns_ledger import account_xirr, holding_returns


def greeks_out(price: OptionPrice | None) -> OptionGreeksOut | None:
    """Per-share Greeks for the wire, rounded to 6 places; None stays None."""
    if price is None:
        return None
    return OptionGreeksOut(
        delta=round(price.delta, 6),
        gamma=round(price.gamma, 6),
        theta=round(price.theta, 6),
        vega=round(price.vega, 6),
        rho=round(price.rho, 6),
    )


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
        fees_paid=snap.fees_paid,
        realized_pl_net=snap.realized_pl_net,
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
                greeks=greeks_out(o.greeks),
                side=o.side,  # type: ignore[arg-type]
                strategy=o.strategy,
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
    portfolio: Portfolio,
    valuation: PortfolioValuation,
    *,
    risk_free_rate: float,
) -> PortfolioAnalyticsOut:
    """Analytics for one book (A5.1): its own snapshots and opening value."""
    snapshots = list(
        session.exec(
            select(PortfolioSnapshot)
            .where(PortfolioSnapshot.portfolio_id == portfolio.id)
            .order_by(PortfolioSnapshot.date.asc())  # type: ignore[attr-defined]
        )
    )
    # LG-1: the series runs from the fixed opening value, through the nightly
    # snapshots, to the live valuation. The first snapshot cannot stand in for
    # the opening: the nightly job overwrites it if the user traded that day.
    opening = portfolio.opening_nav
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
    started = portfolio.created_at.date()
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
        exposure=_exposure_out(session, valuation),
        attribution=(
            _attribution_out(session, portfolio, valuation) if portfolio is not None else None
        ),
    )


def _exposure_out(session: Session, valuation: PortfolioValuation) -> PortfolioExposureOut:
    tickers = sorted(
        {p.ticker for p in valuation.positions} | {o.ticker for o in valuation.option_positions}
    )
    return PortfolioExposureOut(
        currency=valuation.display_currency,
        method=EXPOSURE_METHOD,
        basis=EXPOSURE_BASIS,
        dimensions=[
            ExposureOut(
                dimension=e.dimension,
                buckets=[
                    ExposureBucketOut(
                        key=b.key,
                        equity_value=b.equity_value,
                        cash_value=b.cash_value,
                        options_delta=b.options_delta,
                        weight_pct=b.weight_pct,
                        options_delta_pct=b.options_delta_pct,
                    )
                    for b in e.buckets
                ],
            )
            for e in compute_exposure(valuation, classifications(session, tickers))
        ],
    )


def _attribution_out(
    session: Session, portfolio: Portfolio, valuation: PortfolioValuation
) -> PortfolioAttributionOut:
    return PortfolioAttributionOut(
        currency=valuation.base_currency,
        method=ATTRIBUTION_METHOD,
        basis=ATTRIBUTION_BASIS,
        holdings=[
            HoldingAttributionOut(
                ticker=a.ticker,
                currency=a.currency,
                entry_rate=a.entry_rate,
                rate_now=a.rate_now,
                cost_base=a.cost_base,
                value_base=a.value_base,
                price_effect=a.price_effect,
                currency_effect=a.currency_effect,
                cross_effect=a.cross_effect,
                income=a.income,
                reason=a.reason,
            )
            for a in attribute(session, portfolio, valuation)
        ],
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


# ---------------------------------------------------------------------------
# All books (A5.2)
# ---------------------------------------------------------------------------

PER_BOOK_ONLY = [
    "risk (VaR, CVaR, Monte Carlo)",
    "stress tests",
    "currency attribution",
    "each holding's XIRR",
    "pre-trade limits",
    "dividends",
    "options Greeks and strategies",
    "the journal",
]


def combined_portfolio_response(view: CombinedView) -> PortfolioOut:
    """``PortfolioOut`` for ``?book=all``: the merged valuation plus each book's share."""
    out = portfolio_response(view.valuation, base_currency_locked=True)
    out.combined = CombinedOut(
        books=[
            CombinedBookOut(
                id=b.id,  # type: ignore[arg-type]
                name=b.name,
                kind=str(b.kind),  # type: ignore[arg-type]
                base_currency=b.base_currency or "USD",
                archived=b.archived_at is not None,
                is_default=b.is_default,
                total_value=v.total_value,
            )
            for b, v in zip(view.books, view.valuations, strict=True)
        ],
        fx_rule=FX_STALE_RULE,
        per_book_only=PER_BOOK_ONLY,
    )
    return out


def combined_analytics_response(
    session: Session, view: CombinedView, *, risk_free_rate: float
) -> PortfolioAnalyticsOut:
    """Analytics over every book in the display currency (``services/books/combined.py``).

    Total return, drawdown and Sharpe read the flow-free growth index, so a
    new book or an imported buy is never a gain. Attribution and each
    holding's XIRR are per book only.
    """
    valuation = view.valuation
    series = view.series
    as_of = utcnow().date()
    points = series.points
    index = growth_index(points, series.flows)
    # Like one book: no track record before two snapshot dates (plus today).
    navs = [v for _, v in index] if len(points) >= 3 else []
    opened = series.opened or as_of
    history_days = max((as_of - opened).days, 0)

    tickers = [p.ticker for p in valuation.positions]
    sectors_by_ticker: dict[str, str | None] = (
        dict(
            session.exec(
                select(Symbol.ticker, Symbol.sector).where(
                    Symbol.ticker.in_(tickers)  # type: ignore[attr-defined]
                )
            ).all()  # type: ignore[arg-type]
        )
        if tickers
        else {}
    )
    allocation = compute_sector_allocation(valuation.positions, sectors_by_ticker=sectors_by_ticker)
    gainers, losers = compute_top_movers(valuation.positions, sectors_by_ticker=sectors_by_ticker)
    live = Decimal(valuation.total_value)
    flows = series.flows
    return PortfolioAnalyticsOut(
        display_currency=valuation.display_currency,
        history_days=history_days,
        total_return_pct=compute_total_return_pct(navs),
        annualised_return_pct=(
            compute_annualised_return_pct(navs, days=history_days) if history_days else None
        ),
        # The index without today's live point: end-of-day values only.
        sharpe_ratio=compute_sharpe(index[:-1], risk_free_rate=risk_free_rate)
        if len(index) > 1
        else None,
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
        returns=PortfolioReturnsOut(
            currency=valuation.display_currency,
            twr_method=TWR_METHOD,
            twr_basis=COMBINED_TWR_BASIS,
            periods=[
                PeriodReturnOut(
                    period=r.period,
                    start_date=r.start_date,
                    end_date=r.end_date,
                    return_pct=r.return_pct,
                    annualised_pct=r.annualised_pct,
                    reason=r.reason,
                )
                for r in period_returns(points, as_of=as_of, opened=opened, flows=flows)
            ]
            if points
            else [],
            xirr_method=XIRR_METHOD,
            xirr_basis=COMBINED_XIRR_BASIS,
            account_xirr=_xirr_out(
                xirr(combined_xirr_flows(series, live=live, as_of=as_of), as_of=as_of)
            ),
            holdings=[],
        ),
        exposure=_exposure_out(session, valuation),
        attribution=None,
    )
