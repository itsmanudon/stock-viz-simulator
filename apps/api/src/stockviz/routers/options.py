"""`/v1/options/trade` and `/v1/options/positions` — options paper trading.

Long-only book: open a call/put (premium debited from portfolio cash), close
it back at theoretical value, or let the settlement job resolve it at expiry.
Both endpoints mutate per-user data so they depend on ``UserIdDep``.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlmodel import Session, select

from stockviz.auth import UserIdDep
from stockviz.db import get_session
from stockviz.limiter import limiter
from stockviz.models import (
    OptionCover,
    OptionSide,
    OptionsPosition,
    OptionStatus,
    OptionType,
    Symbol,
)
from stockviz.models.option import CONTRACT_MULTIPLIER, position_sign
from stockviz.models.option_strategy import OptionStrategy, StrategyKind
from stockviz.routers.book_query import BookQuery
from stockviz.schemas import (
    DistributionPointOut,
    ExpiryGroupOut,
    ExpiryItemOut,
    ImpliedDistributionOut,
    OptionExposureOut,
    OptionGreeksOut,
    OptionImpliedVolOut,
    OptionPositionOut,
    OptionQuoteOut,
    OptionRiskOut,
    OptionsBookOut,
    OptionStrategyIn,
    OptionStrategyLegOut,
    OptionStrategyOut,
    OptionStrategyPayoffOut,
    OptionStrategyQuoteOut,
    OptionStrategyRiskOut,
    OptionStrategyTradeOut,
    OptionSurfaceOut,
    OptionTradeIn,
    OptionTradeOut,
    PayoffPointOut,
    SurfaceExpiryOut,
    SurfacePointOut,
    UnderlyingGreeksOut,
    VolSummaryOut,
)
from stockviz.services.options import (
    RISK_FREE_RATE,
    InsufficientCashForOption,
    InsufficientCoverForOption,
    InvalidExpiry,
    NoOptionMarketData,
    OptionNotFound,
    OptionOrderConflict,
    OptionPrice,
    OptionSymbolNotFound,
    OptionTradeError,
    close_option,
    implied_volatility_for,
    open_option,
    quote_option,
    value_option,
)
from stockviz.services.options.book import options_book
from stockviz.services.options.payoff import strategy_payoff
from stockviz.services.options.strategies import LABELS as STRATEGY_LABELS
from stockviz.services.options.strategies import (
    StrategyQuote,
    close_strategy,
    open_strategy,
    quote_strategy,
    strategy_legs,
)
from stockviz.services.risk.limits import LimitBreached
from stockviz.services.trading.books import resolve_book
from stockviz.services.trading.buying_power import put_collateral_usd
from stockviz.services.trading.execute import NoFxRateError
from stockviz.services.trading.portfolio import signed_greeks
from stockviz.services.trading.views import greeks_out

router = APIRouter(prefix="/v1/options", tags=["options"])

SessionDep = Annotated[Session, Depends(get_session)]

_ZERO_GREEKS = OptionGreeksOut(delta=0.0, gamma=0.0, theta=0.0, vega=0.0, rho=0.0)


def _greeks(price: OptionPrice) -> OptionGreeksOut:
    out = greeks_out(price)
    assert out is not None
    return out


def _to_out(session: Session, position: OptionsPosition) -> OptionPositionOut:
    """Build the wire shape, valuing the position at the current Black-Scholes price."""
    try:
        price = value_option(session, position)
        current_value = (
            Decimal(str(price.value)) * position.shares_per_contract * position.quantity
        ).quantize(Decimal("0.01"))
        if current_value < 0:
            current_value = Decimal("0.00")
        # A short leg is a liability: its value and Greeks are negated (Phase 9.2).
        sign = position_sign(position)
        current_value = current_value * sign
        signed = signed_greeks(price, sign)
        assert signed is not None
        greeks = _greeks(signed)
    except NoOptionMarketData:
        current_value = Decimal("0.00")
        greeks = _ZERO_GREEKS

    is_open = position.status == OptionStatus.OPEN
    covered_shares = (
        position.quantity * position.shares_per_contract
        if is_open and position.cover == OptionCover.SHARES
        else Decimal(0)
    )
    collateral = (
        put_collateral_usd(position)
        if is_open and position.cover == OptionCover.CASH
        else Decimal(0)
    )
    return OptionPositionOut(
        id=position.id,  # type: ignore[arg-type]
        ticker=position.ticker,
        option_type=position.option_type.value,  # type: ignore[arg-type]
        strike=position.strike,
        expiry=position.expiry,
        quantity=position.quantity,
        premium_paid=position.premium_paid,
        status=position.status.value,  # type: ignore[arg-type]
        opened_at=position.opened_at,
        current_value=current_value,
        greeks=greeks,
        side=str(position.side),  # type: ignore[arg-type]
        cover=str(position.cover) if position.cover else None,  # type: ignore[arg-type]
        collateral=collateral,
        shares_reserved=covered_shares,
        strategy_id=position.strategy_id,
        covering_leg_id=position.covering_leg_id,
    )


@router.get("/quote", response_model=OptionQuoteOut)
@limiter.limit("60/minute")
def get_option_quote(
    request: Request,
    session: SessionDep,
    ticker: Annotated[str, Query(min_length=1, max_length=16)],
    option_type: Annotated[OptionType, Query()],
    expiry: Annotated[date, Query()],
    strike: Annotated[Decimal | None, Query(gt=0, le=1_000_000_000)] = None,
    quantity: Annotated[int, Query(ge=1, le=1_000)] = 1,
    side: Annotated[OptionSide, Query()] = OptionSide.LONG,
) -> OptionQuoteOut:
    """Price an open without placing it, the way ``POST /trade`` would charge it.

    Public like the other price reads: it uses stored closes only. The ticket
    shows it before the buy (audit LG-7). Without ``strike`` it prices at the
    money and returns the strike it used.
    """
    del request  # slowapi reads it
    try:
        quote = quote_option(
            session,
            ticker=ticker,
            option_type=option_type,
            strike=strike,
            expiry=expiry,
            quantity=quantity,
            side=side,
        )
    except OptionSymbolNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except NoOptionMarketData as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    except (InvalidExpiry, OptionTradeError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    price = quote.price
    risk = quote.risk
    assert risk is not None
    return OptionQuoteOut(
        ticker=quote.ticker,
        option_type=option_type.value,  # type: ignore[arg-type]
        strike=quote.strike,
        expiry=expiry,
        quantity=quantity,
        spot=quote.spot,
        spot_at=quote.spot_at,
        volatility=round(quote.volatility, 6),
        risk_free_rate=RISK_FREE_RATE,
        per_share=quote.per_share.quantize(Decimal("0.000001")),
        premium=quote.premium,
        contract_size=int(CONTRACT_MULTIPLIER),
        greeks=_greeks(price),
        volatility_method=quote.volatility_method,
        volatility_closes=quote.closes_used,
        premium_floor_applied=quote.floored,
        side=side.value,  # type: ignore[arg-type]
        risk=OptionRiskOut(
            collateral=risk.collateral,
            shares_reserved=risk.shares_reserved,
            max_loss=risk.max_loss,
            max_gain=risk.max_gain,
            breakeven=risk.breakeven,
            basis=risk.basis,
        ),
    )


@router.get("/implied-volatility", response_model=OptionImpliedVolOut)
@limiter.limit("60/minute")
def get_implied_volatility(
    request: Request,
    session: SessionDep,
    ticker: Annotated[str, Query(min_length=1, max_length=16)],
    option_type: Annotated[OptionType, Query()],
    expiry: Annotated[date, Query()],
    strike: Annotated[Decimal, Query(gt=0, le=1_000_000_000)],
    price: Annotated[Decimal, Query(gt=0, le=1_000_000_000)],
) -> OptionImpliedVolOut:
    """The volatility at which Black-Scholes gives ``price`` per share (Phase 9.1).

    For a premium the user saw elsewhere: it is solved against the same spot,
    rate and day count StockViz prices with, and returned beside the
    historical volatility StockViz uses. Nothing is stored.
    """
    del request  # slowapi reads it
    try:
        quote = quote_option(
            session, ticker=ticker, option_type=option_type, strike=strike, expiry=expiry
        )
    except OptionSymbolNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except NoOptionMarketData as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    except (InvalidExpiry, OptionTradeError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    solved = implied_volatility_for(quote, expiry=expiry, price=price, option_type=option_type)
    return OptionImpliedVolOut(
        ticker=quote.ticker,
        option_type=option_type.value,  # type: ignore[arg-type]
        strike=quote.strike,
        expiry=expiry,
        per_share_price=price,
        spot=quote.spot,
        spot_at=quote.spot_at,
        risk_free_rate=RISK_FREE_RATE,
        implied_volatility=(round(solved.volatility, 6) if solved.volatility is not None else None),
        reason=solved.reason,
        historical_volatility=round(quote.volatility, 6),
    )


@router.post("/trade", response_model=OptionTradeOut, status_code=status.HTTP_201_CREATED)
def post_options_trade(
    body: OptionTradeIn, session: SessionDep, user_id: UserIdDep, book: BookQuery = None
) -> OptionTradeOut:
    """Open in ``?book=`` (default book); a close trades in the leg's own book."""
    if body.action == "open":
        missing = [
            name
            for name, value in (
                ("ticker", body.ticker),
                ("option_type", body.option_type),
                ("strike", body.strike),
                ("expiry", body.expiry),
                ("quantity", body.quantity),
            )
            if value is None
        ]
        if missing:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"action 'open' requires: {', '.join(missing)}",
            )
        try:
            result = open_option(
                session,
                user_id=user_id,
                ticker=body.ticker,  # type: ignore[arg-type]
                option_type=OptionType(body.option_type),
                strike=body.strike,  # type: ignore[arg-type]
                expiry=body.expiry,  # type: ignore[arg-type]
                quantity=body.quantity,  # type: ignore[arg-type]
                client_order_id=body.client_order_id,
                side=OptionSide(body.side),
                book_id=book,
            )
        except OptionOrderConflict as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
        except LimitBreached as exc:
            session.rollback()
            raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
        except OptionSymbolNotFound as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
        except (
            InsufficientCashForOption,
            InsufficientCoverForOption,
            NoOptionMarketData,
            NoFxRateError,
        ) as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
        except (InvalidExpiry, OptionTradeError) as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    else:  # close
        if body.option_id is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "action 'close' requires: option_id")
        try:
            result = close_option(session, user_id=user_id, option_id=body.option_id)
        except OptionNotFound as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
        except (NoOptionMarketData, InsufficientCashForOption, NoFxRateError) as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
        except OptionTradeError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    return OptionTradeOut(
        position=_to_out(session, result.position),
        cash_delta=result.cash_delta,
    )


@router.get("/positions", response_model=list[OptionPositionOut])
def list_options_positions(
    session: SessionDep, user_id: UserIdDep, book: BookQuery = None
) -> list[OptionPositionOut]:
    """Return the book's open options positions, newest first, each priced now."""
    portfolio = resolve_book(session, user_id, book)
    rows = list(
        session.exec(
            select(OptionsPosition)
            .where(
                OptionsPosition.portfolio_id == portfolio.id,
                OptionsPosition.status == OptionStatus.OPEN,
            )
            .order_by(OptionsPosition.opened_at.desc())  # type: ignore[attr-defined]
        )
    )
    return [_to_out(session, position) for position in rows]


# ---------------------------------------------------------------------------
# Strategies (Phase 9.3)
# ---------------------------------------------------------------------------


def _strategy_args(body: OptionStrategyIn) -> dict:
    return {
        "kind": StrategyKind(body.kind),
        "ticker": body.ticker,
        "strikes": body.strikes,
        "expiry": body.expiry,
        "quantity": body.quantity,
        "far_expiry": body.far_expiry,
        "option_type": OptionType(body.option_type) if body.option_type else None,
    }


def _strategy_errors(exc: Exception) -> HTTPException:
    if isinstance(exc, OptionNotFound | OptionSymbolNotFound):
        return HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    if isinstance(exc, OptionOrderConflict | LimitBreached):
        return HTTPException(status.HTTP_409_CONFLICT, str(exc))
    if isinstance(
        exc,
        InsufficientCashForOption | InsufficientCoverForOption | NoOptionMarketData | NoFxRateError,
    ):
        return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))
    return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


_STRATEGY_ERRORS = (
    OptionTradeError,
    InvalidExpiry,
    NoOptionMarketData,
    NoFxRateError,
    LimitBreached,
)


def _strategy_out(session: Session, strategy: OptionStrategy) -> OptionStrategyOut:
    return OptionStrategyOut(
        id=strategy.id,  # type: ignore[arg-type]
        kind=strategy.kind,
        label=STRATEGY_LABELS[StrategyKind(strategy.kind)],
        status=strategy.status,
        net_premium=strategy.net_premium,
        collateral=strategy.collateral,
        max_loss=strategy.max_loss,
        max_gain=strategy.max_gain,
        opened_at=strategy.opened_at,
        legs=[_to_out(session, leg) for leg in strategy_legs(session, strategy)],
    )


@router.post("/strategies/quote", response_model=OptionStrategyQuoteOut)
@limiter.limit("60/minute")
def post_strategy_quote(
    request: Request, body: OptionStrategyIn, session: SessionDep
) -> OptionStrategyQuoteOut:
    """Price a strategy without opening it: every leg, the net premium, what it
    holds back, the most it can lose and gain, and the breakevens. Public."""
    del request  # slowapi reads it
    try:
        quote = quote_strategy(session, **_strategy_args(body))
    except _STRATEGY_ERRORS as exc:
        raise _strategy_errors(exc) from exc
    return _quote_out(quote)


def _quote_out(quote: StrategyQuote) -> OptionStrategyQuoteOut:
    first = quote.legs[0][1]
    risk = quote.risk
    return OptionStrategyQuoteOut(
        kind=quote.kind.value,
        label=STRATEGY_LABELS[quote.kind],
        ticker=quote.ticker,
        quantity=quote.quantity,
        spot=first.spot,
        spot_at=first.spot_at,
        legs=[
            OptionStrategyLegOut(
                side=plan.side.value,  # type: ignore[arg-type]
                option_type=plan.option_type.value,  # type: ignore[arg-type]
                strike=plan.strike,
                expiry=plan.expiry,
                per_share=q.per_share.quantize(Decimal("0.000001")),
                premium=q.premium,
            )
            for plan, q in quote.legs
        ],
        risk=OptionStrategyRiskOut(
            net_premium=risk.net_premium,
            collateral=risk.collateral,
            shares_reserved=quote.shares_reserved,
            max_loss=risk.max_loss,
            max_gain=risk.max_gain,
            breakevens=list(risk.breakevens),
            basis=risk.basis,
        ),
    )


@router.post(
    "/strategies", response_model=OptionStrategyTradeOut, status_code=status.HTTP_201_CREATED
)
def post_strategy(
    body: OptionStrategyIn, session: SessionDep, user_id: UserIdDep, book: BookQuery = None
) -> OptionStrategyTradeOut:
    """Open every leg of a strategy in one transaction, or none, in ``?book=``."""
    try:
        result = open_strategy(
            session,
            user_id=user_id,
            client_order_id=body.client_order_id,
            book_id=book,
            **_strategy_args(body),
        )
    except _STRATEGY_ERRORS as exc:
        session.rollback()
        raise _strategy_errors(exc) from exc
    return OptionStrategyTradeOut(
        strategy=_strategy_out(session, result.strategy), cash_delta=result.cash_delta
    )


@router.get("/strategies", response_model=list[OptionStrategyOut])
def list_strategies(
    session: SessionDep, user_id: UserIdDep, book: BookQuery = None
) -> list[OptionStrategyOut]:
    portfolio = resolve_book(session, user_id, book)
    rows = session.exec(
        select(OptionStrategy)
        .where(OptionStrategy.portfolio_id == portfolio.id)
        .order_by(OptionStrategy.opened_at.desc())  # type: ignore[attr-defined]
    ).all()
    return [_strategy_out(session, row) for row in rows]


@router.post("/strategies/{strategy_id}/close", response_model=OptionStrategyTradeOut)
def post_strategy_close(
    strategy_id: int, session: SessionDep, user_id: UserIdDep
) -> OptionStrategyTradeOut:
    """Close every open leg at its model value: long legs sold, short legs bought back."""
    try:
        result = close_strategy(session, user_id=user_id, strategy_id=strategy_id)
    except (*_STRATEGY_ERRORS, OptionNotFound) as exc:
        session.rollback()
        raise _strategy_errors(exc) from exc
    return OptionStrategyTradeOut(
        strategy=_strategy_out(session, result.strategy), cash_delta=result.cash_delta
    )


@router.post("/strategies/payoff", response_model=OptionStrategyPayoffOut)
@limiter.limit("60/minute")
def post_strategy_payoff(
    request: Request,
    body: OptionStrategyIn,
    session: SessionDep,
    days_forward: Annotated[int | None, Query(ge=0, le=3650)] = None,
    iv_shift: Annotated[float, Query(ge=-0.5, le=2.0)] = 0.0,
) -> OptionStrategyPayoffOut:
    """The quote plus its payoff curves and model chance of profit. Public."""
    del request  # slowapi reads it
    try:
        quote = quote_strategy(session, **_strategy_args(body))
    except _STRATEGY_ERRORS as exc:
        raise _strategy_errors(exc) from exc
    payoff = strategy_payoff(quote, days_forward=days_forward, iv_shift=iv_shift)
    return OptionStrategyPayoffOut(
        quote=_quote_out(quote),
        horizon=payoff.horizon,
        points=[
            PayoffPointOut(spot=p.spot, at_expiry=p.at_expiry, today=p.today, what_if=p.what_if)
            for p in payoff.points
        ],
        prob_profit=payoff.prob_profit,
        volatility=round(payoff.volatility, 6),
        method=payoff.method,
    )


@router.get("/{ticker}/exposure", response_model=OptionExposureOut)
@limiter.limit("60/minute")
def get_option_exposure(request: Request, ticker: str, session: SessionDep) -> OptionExposureOut:
    """A7.9 (M6.2): gamma and delta exposure, the gamma flip, the walls and the
    IV-implied one-day move, from the newest stored chain. Public."""
    from stockviz.services.options.exposure import NOTE, exposure

    del request  # slowapi reads it
    if session.get(Symbol, ticker.upper()) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Symbol {ticker.upper()!r} not found")
    e = exposure(session, ticker)
    return OptionExposureOut(**{**e.__dict__, "note": NOTE})  # type: ignore[arg-type]


VOL_SUMMARY_METHOD = (
    "From the stored nightly chains: ATM IV per expiry, 25-delta skew (put minus call IV), "
    "VRP = the ~30-day ATM IV minus 21-session realised volatility, and IV rank and "
    "percentile over the stored snapshots of the last year (20 at least). Context, not a "
    "signal on its own."
)


@router.get("/{ticker}/vol-summary", response_model=VolSummaryOut)
@limiter.limit("60/minute")
def get_vol_summary(request: Request, ticker: str, session: SessionDep) -> VolSummaryOut:
    """A9.4 (M6.3): term structure, skew, VRP and IV rank. Public."""
    from stockviz.services.options.vol_summary import vol_summary

    del request
    if session.get(Symbol, ticker.upper()) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Symbol {ticker.upper()!r} not found")
    v = vol_summary(session, ticker)
    return VolSummaryOut.model_validate({**v.__dict__, "method": VOL_SUMMARY_METHOD})


@router.get("/book", response_model=OptionsBookOut)
def get_options_book(
    session: SessionDep, user_id: UserIdDep, book: BookQuery = None
) -> OptionsBookOut:
    """The options book's Greeks and its legs by expiry (Phase 9.5), per book (A5.1)."""
    greeks = options_book(session, resolve_book(session, user_id, book))
    return OptionsBookOut(
        underlyings=[
            UnderlyingGreeksOut(
                ticker=u.ticker,
                spot=u.spot,
                delta_shares=round(u.delta_shares, 4),
                dollar_delta=round(u.dollar_delta, 2),
                gamma_shares=round(u.gamma_shares, 4),
                theta_per_day=round(u.theta_per_day, 2),
                vega_per_point=round(u.vega_per_point, 2),
                rho_per_point=round(u.rho_per_point, 2),
            )
            for u in greeks.underlyings
        ],
        dollar_delta=round(greeks.dollar_delta, 2),
        theta_per_day=round(greeks.theta_per_day, 2),
        vega_per_point=round(greeks.vega_per_point, 2),
        rho_per_point=round(greeks.rho_per_point, 2),
        expirations=[
            ExpiryGroupOut(
                expiry=expiry,
                items=[
                    ExpiryItemOut(
                        label=i.label,
                        legs=i.legs,
                        at_risk=i.at_risk,
                        outcome=i.outcome,
                        net_cash=i.net_cash,
                        strategy_id=i.strategy_id,
                    )
                    for i in items
                ],
            )
            for expiry, items in greeks.expirations
        ],
        unpriced=greeks.unpriced,
        method=(
            "Black-Scholes Greeks at the latest close with 30-session historical volatility, "
            "summed over open legs (short legs negated); outcomes assume the stock closes at "
            "today's price on each expiry"
        ),
    )


@router.get("/surface", response_model=OptionSurfaceOut)
@limiter.limit("30/minute")
def get_option_surface(
    request: Request,
    session: SessionDep,
    ticker: Annotated[str, Query(min_length=1, max_length=16)],
) -> OptionSurfaceOut:
    """Implied volatility by expiry and strike from the latest chain snapshot. Public."""
    from stockviz.services.options.chains import surface
    from stockviz.services.options.trade import _spot, _today

    del request  # slowapi reads it
    ticker = ticker.upper()
    found = surface(session, ticker, asof=_today())
    source = "yfinance option chains, stored nightly (Phase 9.6); IV solved from the bid-ask mid"
    if found is None:
        return OptionSurfaceOut(
            ticker=ticker, snapshot_date=None, spot=None, expiries=[], source=source
        )
    snapshot_date, expiries = found
    return OptionSurfaceOut(
        ticker=ticker,
        snapshot_date=snapshot_date,
        spot=_spot(session, ticker),
        expiries=[
            SurfaceExpiryOut(
                expiry=expiry,
                points=[
                    SurfacePointOut(
                        strike=p.strike,
                        call_iv=None if p.call_iv is None else round(p.call_iv, 6),
                        put_iv=None if p.put_iv is None else round(p.put_iv, 6),
                    )
                    for p in points
                ],
            )
            for expiry, points in expiries
        ],
        source=source,
    )


IMPLIED_METHOD = (
    "Implied: the risk-neutral density from the newest stored chain by Breeden-Litzenberger "
    "(e^rT times the second derivative of Black-Scholes call prices in strike), on the "
    "out-of-the-money IV smile interpolated linearly in strike and flat beyond it. Model: a "
    "lognormal with the HAR-RV forecast volatility (else 21-session realised) and the same "
    "forward. The implied density includes the market's risk premium; it is not a forecast."
)


@router.get("/{ticker}/implied-distribution", response_model=ImpliedDistributionOut)
@limiter.limit("60/minute")
def get_implied_distribution(
    request: Request, ticker: str, session: SessionDep, expiry: date | None = None
) -> ImpliedDistributionOut:
    """A9.13 (M8.5): option-implied vs model distribution of the price at expiry."""
    from stockviz.services.options import implied_distribution as idist

    del request
    t = ticker.upper()
    if session.get(Symbol, t) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Symbol {t!r} not found")
    d = idist.load(session, t, expiry)
    return ImpliedDistributionOut(
        ticker=t,
        expiry=d.expiry,
        days=d.days,
        spot=d.spot,
        implied_atm_vol=d.implied_atm_vol,
        model_vol=d.model_vol,
        model_vol_source=d.model_vol_source,
        quantile_levels=list(idist.QUANTILES),
        implied_quantiles=d.implied_quantiles,
        model_quantiles=d.model_quantiles,
        move=idist.MOVE,
        implied_p_down=d.implied_p_down,
        implied_p_up=d.implied_p_up,
        model_p_down=d.model_p_down,
        model_p_up=d.model_p_up,
        negative_mass=d.negative_mass,
        strikes_used=d.strikes_used,
        curve=[DistributionPointOut(price=a, implied=b, model=c) for a, b, c in d.curve],
        reason=d.reason,
        method=IMPLIED_METHOD,
    )
