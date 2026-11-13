"""`/v1/portfolio` and `/v1/trades` — paper-trading endpoints.

These mutate user data so they're gated on the internal-token dependency
(see ``stockviz.auth``). The web app's Next.js server is the only caller
that should know the token; the browser never sees it.
"""

from __future__ import annotations

from datetime import date as date_type
from datetime import timedelta
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel import Session, select

from stockviz._time import utcnow
from stockviz.auth import UserIdDep
from stockviz.db import get_session
from stockviz.models import (
    PortfolioSnapshot,
    Position,
    SimulatedExecution,
    Symbol,
    Trade,
    TradeSide,
    User,
)
from stockviz.models.dividend import Dividend, PortfolioDividend
from stockviz.models.risk_limit import LIMIT_COLUMNS as RISK_LIMIT_COLUMNS
from stockviz.models.risk_limit import RiskLimit
from stockviz.schemas import (
    BaseCurrencyIn,
    DividendCreditOut,
    DividendSummaryOut,
    ExecutionProvenanceOut,
    LimitCheckOut,
    LimitPreviewOut,
    MonteCarloOut,
    PortfolioAnalyticsOut,
    PortfolioHistoryPointOut,
    PortfolioOut,
    PortfolioOverviewOut,
    PortfolioRiskOut,
    PortfolioStressOut,
    ProjectedDividendOut,
    RiskLimitsIn,
    RiskLimitsOut,
    RiskNoteOut,
    RiskProxyOut,
    RiskWindowOut,
    StressDriverOut,
    StressScenarioOut,
    TradeIn,
    TradeOut,
    VarOut,
)
from stockviz.services.instruments import instrument_of
from stockviz.services.risk import compute_risk
from stockviz.services.risk.engine import MC_METHOD, VAR_METHOD
from stockviz.services.risk.limits import LimitBreached, check_buy
from stockviz.services.risk.stress import STRESS_METHOD, run_stress
from stockviz.services.trading import (
    ClientOrderIdConflict,
    InsufficientCash,
    InsufficientPosition,
    NoFxRateError,
    NoMarketDataError,
    StaleMarketData,
    SymbolNotFound,
    TradeExecutionError,
    compute_portfolio,
    ensure_default_portfolio,
    execute_trade,
)
from stockviz.services.trading.account import (
    AccountNotFresh,
    UnsupportedBaseCurrency,
    set_base_currency,
)
from stockviz.services.trading.account import activity as account_activity
from stockviz.services.trading.execute import resolve_priced_symbol
from stockviz.services.trading.fx import convert as fx_convert
from stockviz.services.trading.fx import latest_rate as fx_latest_rate
from stockviz.services.trading.simulation_adapter import as_aware_utc
from stockviz.services.trading.views import portfolio_analytics_response, portfolio_response

router = APIRouter(prefix="/v1", tags=["trading"])

SessionDep = Annotated[Session, Depends(get_session)]


def _user_display_currency(session: Session, user_id: int) -> str:
    user = session.get(User, user_id)
    return (user.display_currency if user else None) or "USD"


@router.get("/portfolio", response_model=PortfolioOut)
def get_portfolio(session: SessionDep, user_id: UserIdDep) -> PortfolioOut:
    portfolio = ensure_default_portfolio(session, user_id)
    display = _user_display_currency(session, user_id)
    snap = compute_portfolio(session, portfolio, display_currency=display)
    return portfolio_response(snap, base_currency_locked=bool(account_activity(session, portfolio)))


@router.put("/portfolio/base-currency", response_model=PortfolioOut)
def put_base_currency(
    body: BaseCurrencyIn, session: SessionDep, user_id: UserIdDep
) -> PortfolioOut:
    """Restart a fresh account in USD ($100,000) or INR (₹1 crore) — Phase 4.8.

    409 once the account has any trade, order, option, dividend or foreign
    cash. Also sets the display currency to the new base.
    """
    try:
        portfolio = set_base_currency(session, user_id=user_id, currency=body.base_currency)
    except UnsupportedBaseCurrency as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except AccountNotFresh as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    display = _user_display_currency(session, user_id)
    snap = compute_portfolio(session, portfolio, display_currency=display)
    return portfolio_response(snap, base_currency_locked=bool(account_activity(session, portfolio)))


@router.post("/trades", response_model=TradeOut, status_code=status.HTTP_201_CREATED)
def post_trade(body: TradeIn, session: SessionDep, user_id: UserIdDep) -> TradeOut:
    try:
        side = TradeSide(body.side)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Invalid side: {body.side!r}") from exc

    try:
        result = execute_trade(
            session,
            user_id=user_id,
            ticker=body.ticker,
            side=side,
            quantity=body.quantity,
            client_order_id=body.client_order_id,
        )
    except SymbolNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except LimitBreached as exc:
        session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except (StaleMarketData, ClientOrderIdConflict) as exc:
        # 409: the market or an earlier order conflicts with this one (#67).
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except (InsufficientCash, InsufficientPosition, NoMarketDataError, NoFxRateError) as exc:
        # 422: request was well-formed but couldn't be honored against the
        # current portfolio / market / FX state.
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    except TradeExecutionError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    trade = result.trade
    return TradeOut(
        id=trade.id,  # type: ignore[arg-type]
        ticker=trade.ticker,
        side=trade.side.value,  # type: ignore[arg-type]
        quantity=trade.quantity,
        price=trade.price,
        ts=trade.ts,
        currency=result.currency,
        fx_rate=result.fx_rate,
        total_native=result.native_cost,
        total_usd=_usd_total(session, result.base_cost, result.base_currency),
        base_currency=result.base_currency,
        total_base=result.base_cost,
        realized_pnl=result.realized_pnl,
    )


def _usd_total(session: Session, amount: Decimal, base: str) -> Decimal:
    """``total_usd`` for an INR book: the base amount at the latest rate."""
    if base == "USD":
        return amount
    try:
        return amount * fx_latest_rate(session, base)
    except LookupError:
        return amount


DEFAULT_RISK_FREE_RATE = 0.05
"""Annual risk-free rate used by the Sharpe calculation when callers don't override it."""


@router.get("/portfolio/analytics", response_model=PortfolioAnalyticsOut)
def get_portfolio_analytics(
    session: SessionDep,
    user_id: UserIdDep,
    risk_free_rate: Annotated[float, Query(ge=0, le=1)] = DEFAULT_RISK_FREE_RATE,
) -> PortfolioAnalyticsOut:
    """Return Sharpe, drawdown, returns, sector mix, and top movers.

    Time-series metrics use every snapshot the user has; the series can be
    empty for brand-new accounts (in which case those fields come back as
    ``None`` and the UI hides the relevant cards).
    """
    portfolio = ensure_default_portfolio(session, user_id)
    display = _user_display_currency(session, user_id)
    valuation = compute_portfolio(session, portfolio, display_currency=display)

    return portfolio_analytics_response(session, user_id, valuation, risk_free_rate=risk_free_rate)


@router.get("/portfolio/overview", response_model=PortfolioOverviewOut)
def get_portfolio_overview(
    session: SessionDep,
    user_id: UserIdDep,
    risk_free_rate: Annotated[float, Query(ge=0, le=1)] = DEFAULT_RISK_FREE_RATE,
) -> PortfolioOverviewOut:
    """Build summary and analytics from one uncached valuation for this user."""
    portfolio = ensure_default_portfolio(session, user_id)
    display = _user_display_currency(session, user_id)
    valuation = compute_portfolio(session, portfolio, display_currency=display)
    return PortfolioOverviewOut(
        portfolio=portfolio_response(
            valuation, base_currency_locked=bool(account_activity(session, portfolio))
        ),
        analytics=portfolio_analytics_response(
            session, user_id, valuation, risk_free_rate=risk_free_rate
        ),
    )


VAR_RULE = (
    "VaR is the k-th worst scenario loss, k = ceil(scenarios x (1 - confidence)); "
    "CVaR is the mean of those k losses"
)


@router.get("/portfolio/risk", response_model=PortfolioRiskOut)
def get_portfolio_risk(session: SessionDep, user_id: UserIdDep) -> PortfolioRiskOut:
    """Phase 8.3: historical-simulation VaR/CVaR and a block-bootstrap Monte Carlo.

    Computed on request from stored daily closes and FX rates (about a
    second for a large book). Every figure is in the base currency and the
    response names the method, the window and any proxied holdings.
    """
    portfolio = ensure_default_portfolio(session, user_id)
    display = _user_display_currency(session, user_id)
    valuation = compute_portfolio(session, portfolio, display_currency=display)
    report = compute_risk(session, portfolio, valuation, as_of=utcnow().date())
    sc = report.scenarios
    nav = sc.nav_base
    mc = report.monte_carlo
    return PortfolioRiskOut(
        currency=sc.base_currency,
        nav=nav,
        method=VAR_METHOD,
        var_rule=VAR_RULE,
        window=RiskWindowOut(
            start=sc.dates[0] if sc.dates else None,
            end=sc.dates[-1] if sc.dates else None,
            sessions=len(sc.dates),
        ),
        holdings_included=sc.included,
        excluded=[RiskNoteOut(ticker=e.ticker, reason=e.reason) for e in sc.excluded],
        proxied=[RiskProxyOut(ticker=p.ticker, proxy=p.proxy, days=p.days) for p in sc.proxied],
        var=[
            VarOut(
                confidence=v.confidence,
                horizon_days=v.horizon_days,
                scenarios=v.scenarios,
                tail_count=v.tail_count,
                var=round(v.var, 2),
                var_pct=round(v.var / nav * 100, 4) if nav else 0.0,
                cvar=round(v.cvar, 2),
                cvar_pct=round(v.cvar / nav * 100, 4) if nav else 0.0,
            )
            for v in report.var
        ],
        monte_carlo=(
            MonteCarloOut(
                method=MC_METHOD,
                paths=mc.paths,
                horizon_days=mc.horizon_days,
                mean_block=mc.mean_block,
                seed=mc.seed,
                percentiles={str(k): round(v, 2) for k, v in mc.percentiles.items()},
                prob_loss_10=mc.prob_loss_10,
                prob_loss_20=mc.prob_loss_20,
            )
            if mc is not None
            else None
        ),
        reason=sc.reason,
    )


STRESS_BASIS = (
    "each scenario applied instantly to today's holdings in the base currency: stocks "
    "by the scenario's move, currencies by its rate move, options repriced in full; "
    "a stock without history in a past window takes its index's move times its "
    "two-year beta"
)


@router.get("/portfolio/stress", response_model=PortfolioStressOut)
def get_portfolio_stress(session: SessionDep, user_id: UserIdDep) -> PortfolioStressOut:
    """Phase 8.4: historical replays and hypothetical shocks on today's book."""
    portfolio = ensure_default_portfolio(session, user_id)
    display = _user_display_currency(session, user_id)
    valuation = compute_portfolio(session, portfolio, display_currency=display)
    base = portfolio.base_currency or "USD"
    try:
        nav = float(
            fx_convert(session, valuation.total_value, from_currency=display, to_currency=base)
        )
    except LookupError:
        nav = float(valuation.total_value)
    return PortfolioStressOut(
        currency=base,
        method=STRESS_METHOD,
        basis=STRESS_BASIS,
        scenarios=[
            StressScenarioOut(
                key=r.key,
                name=r.name,
                kind=r.kind,
                start=r.start,
                end=r.end,
                nav_before=round(r.nav_before, 2),
                nav_after=round(r.nav_after, 2),
                change=round(r.change, 2),
                change_pct=round(r.change_pct, 4),
                drivers=[
                    StressDriverOut(ticker=d.ticker, change=round(d.change, 2)) for d in r.drivers
                ],
                proxied=r.proxied,
                missing=r.missing,
            )
            for r in run_stress(session, portfolio, valuation, nav_base=nav)
        ],
    )


def _limits_out(row: RiskLimit | None) -> RiskLimitsOut:
    if row is None:
        return RiskLimitsOut()
    return RiskLimitsOut(
        max_position_pct=row.max_position_pct,
        max_order_pct=row.max_order_pct,
        max_sector_pct=row.max_sector_pct,
        max_currency_pct=row.max_currency_pct,
        max_var_pct=row.max_var_pct,
        updated_at=row.updated_at,
    )


@router.get("/portfolio/limits", response_model=RiskLimitsOut)
def get_risk_limits(session: SessionDep, user_id: UserIdDep) -> RiskLimitsOut:
    """Phase 8.5: the account's own pre-trade limits; all null until set."""
    portfolio = ensure_default_portfolio(session, user_id)
    return _limits_out(session.get(RiskLimit, portfolio.id))


@router.put("/portfolio/limits", response_model=RiskLimitsOut)
def put_risk_limits(session: SessionDep, user_id: UserIdDep, body: RiskLimitsIn) -> RiskLimitsOut:
    """Replace every limit at once; a null clears that limit."""
    portfolio = ensure_default_portfolio(session, user_id)
    assert portfolio.id is not None
    row = session.get(RiskLimit, portfolio.id) or RiskLimit(portfolio_id=portfolio.id)
    for name in RISK_LIMIT_COLUMNS:
        setattr(row, name, getattr(body, name))
    row.updated_at = utcnow()
    session.add(row)
    session.commit()
    session.refresh(row)
    return _limits_out(row)


@router.get("/portfolio/limits/check", response_model=LimitPreviewOut)
def preview_limits(
    session: SessionDep,
    user_id: UserIdDep,
    ticker: Annotated[str, Query(min_length=1, max_length=16)],
    quantity: Annotated[Decimal, Query(gt=0)],
) -> LimitPreviewOut:
    """What buying ``quantity`` of ``ticker`` at the latest close would do to
    each limit (the order review shows it before the user places the order)."""
    portfolio = ensure_default_portfolio(session, user_id)
    base = portfolio.base_currency or "USD"
    try:
        priced = resolve_priced_symbol(session, ticker.upper(), base=base)
    except TradeExecutionError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    base_cost = priced.price * quantity * priced.fx_rate
    checks = check_buy(
        session,
        portfolio,
        ticker=priced.symbol.ticker,
        currency=priced.currency,
        quantity=quantity,
        price=priced.price,
        base_cost=base_cost,
        base_debit=base_cost,
    )
    return LimitPreviewOut(
        ticker=priced.symbol.ticker,
        quantity=quantity,
        checks=[
            LimitCheckOut(
                limit=c.limit,
                label=c.label,
                cap=c.cap,
                value_after=c.value_after,
                breached=c.breached,
                note=c.note,
            )
            for c in checks
        ],
        breached=any(c.breached for c in checks),
    )


@router.get("/portfolio/history", response_model=list[PortfolioHistoryPointOut])
def get_portfolio_history(
    session: SessionDep,
    user_id: UserIdDep,
    days: Annotated[int | None, Query(ge=1, le=3650)] = 90,
) -> list[PortfolioSnapshot]:
    """Return the user's daily NAV history, oldest first.

    ``days=None`` (omit query param) returns the full history; otherwise the
    last N days. Empty list when the scheduler hasn't written any snapshots
    yet for this user — the UI hides the chart in that case.
    """
    stmt = select(PortfolioSnapshot).where(PortfolioSnapshot.user_id == user_id)
    if days is not None:
        cutoff = utcnow().date() - timedelta(days=days)
        stmt = stmt.where(PortfolioSnapshot.date >= cutoff)
    stmt = stmt.order_by(PortfolioSnapshot.date.asc())  # type: ignore[attr-defined]
    return list(session.exec(stmt).all())


@router.get("/trades", response_model=list[TradeOut])
def list_trades(
    session: SessionDep,
    user_id: UserIdDep,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[TradeOut]:
    """Return executed trades, newest first.

    ``fx_rate`` is the rate captured at fill time, so ``total_usd`` is what the
    trade actually cost rather than a re-conversion at today's rate. Rows
    written before that column existed fall back to the symbol's current rate,
    which is the old (approximate) behaviour.
    """
    portfolio = ensure_default_portfolio(session, user_id)
    rows = list(
        session.exec(
            select(Trade)
            .where(Trade.portfolio_id == portfolio.id)
            .order_by(Trade.ts.desc())  # type: ignore[attr-defined]
            .limit(limit)
        )
    )
    if not rows:
        return []

    # One query for every symbol in the page instead of one per trade row.
    tickers = {t.ticker for t in rows}
    currency_by_ticker: dict[str, str] = {
        ticker: (currency or "USD")
        for ticker, currency in session.exec(
            select(Symbol.ticker, Symbol.currency).where(Symbol.ticker.in_(tickers))  # type: ignore[attr-defined]
        ).all()
    }

    base = portfolio.base_currency or "USD"
    out: list[TradeOut] = []
    fx_cache: dict[str, Decimal] = {}
    for trade in rows:
        ccy = currency_by_ticker.get(trade.ticker, "USD")
        rate = trade.fx_rate
        if rate is None:
            if ccy not in fx_cache:
                try:
                    fx_cache[ccy] = fx_latest_rate(session, ccy)
                except LookupError:
                    fx_cache[ccy] = Decimal(1)
            rate = fx_cache[ccy]
        native = trade.price * trade.quantity
        out.append(
            TradeOut(
                id=trade.id,  # type: ignore[arg-type]
                ticker=trade.ticker,
                side=trade.side.value,  # type: ignore[arg-type]
                quantity=trade.quantity,
                price=trade.price,
                ts=trade.ts,
                currency=ccy,
                fx_rate=rate,
                total_native=native,
                total_usd=_usd_total(session, native * rate, base),
                base_currency=base,
                total_base=native * rate,
                realized_pnl=trade.realized_pnl,
            )
        )
    return out


@router.get("/trades/{trade_id}/execution", response_model=ExecutionProvenanceOut)
def get_trade_execution(
    trade_id: int, session: SessionDep, user_id: UserIdDep
) -> ExecutionProvenanceOut:
    """Return kernel provenance for one of the user's live equity fills.

    404 when the trade is missing, not owned by the caller, or was written
    before SIM-04 (no provenance row). Does not change ``GET /v1/trades``.
    """
    portfolio = ensure_default_portfolio(session, user_id)
    trade = session.get(Trade, trade_id)
    if trade is None or trade.portfolio_id != portfolio.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Trade not found")

    row = session.exec(
        select(SimulatedExecution).where(SimulatedExecution.trade_id == trade_id)
    ).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Execution provenance not found")

    return ExecutionProvenanceOut(
        trade_id=row.trade_id,
        profile_name=row.profile_name,
        model_version=row.model_version,
        reference_price=row.reference_price,
        fill_price=row.fill_price,
        reason=row.reason,
        assumptions=list(row.assumptions),
        market_interval=row.market_interval,
        order_type=row.order_type,
        evaluated_at=as_aware_utc(row.evaluated_at),
        created_at=as_aware_utc(row.created_at),
    )


@router.get("/portfolio/dividends", response_model=DividendSummaryOut)
def get_portfolio_dividends(session: SessionDep, user_id: UserIdDep) -> DividendSummaryOut:
    """Return dividend income history and projected next payouts for the user's portfolio."""
    portfolio = ensure_default_portfolio(session, user_id)

    # Credit history, newest first.
    credits = list(
        session.exec(
            select(PortfolioDividend)
            .where(PortfolioDividend.portfolio_id == portfolio.id)
            .order_by(PortfolioDividend.ex_date.desc())  # type: ignore[attr-defined]
        )
    )

    # YTD income (Jan 1 of current year).
    today = utcnow().date()
    ytd_cutoff = date_type(today.year, 1, 1)
    ytd_income = sum(
        (c.base_value for c in credits if c.ex_date >= ytd_cutoff),
        start=Decimal(0),
    )

    # Projected payouts: for each current position find the most recent
    # dividend in the master calendar and estimate the next payment date
    # by adding the observed payment frequency.
    positions = list(
        session.exec(
            select(Position).where(
                Position.portfolio_id == portfolio.id,
                Position.quantity > 0,
            )
        )
    )

    projected: list[ProjectedDividendOut] = []
    for pos in positions:
        recent_divs = list(
            session.exec(
                select(Dividend)
                .where(Dividend.instrument_id == instrument_of(pos.ticker))
                .order_by(Dividend.ex_date.desc())  # type: ignore[attr-defined]
                .limit(5)
            )
        )
        if not recent_divs:
            continue

        last_div = recent_divs[0]
        projected_amount = (pos.quantity * last_div.amount).quantize(last_div.amount)

        # Estimate frequency from the gap between the last two payments.
        projected_ex_date: date_type | None = None
        if len(recent_divs) >= 2:
            gap = (recent_divs[0].ex_date - recent_divs[1].ex_date).days
            if gap > 0:
                projected_ex_date = last_div.ex_date + timedelta(days=gap)

        projected.append(
            ProjectedDividendOut(
                ticker=pos.ticker,
                projected_ex_date=projected_ex_date,
                projected_amount=projected_amount,
            )
        )

    projected.sort(key=lambda p: p.projected_ex_date or date_type.max)

    return DividendSummaryOut(
        ytd_income=ytd_income,
        history=[DividendCreditOut.model_validate(c) for c in credits],
        projected=projected,
    )
