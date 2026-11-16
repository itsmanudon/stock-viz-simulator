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
from stockviz.models import OptionCover, OptionSide, OptionsPosition, OptionStatus, OptionType
from stockviz.models.option import CONTRACT_MULTIPLIER, position_sign
from stockviz.schemas import (
    OptionGreeksOut,
    OptionImpliedVolOut,
    OptionPositionOut,
    OptionQuoteOut,
    OptionRiskOut,
    OptionTradeIn,
    OptionTradeOut,
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
from stockviz.services.risk.limits import LimitBreached
from stockviz.services.trading.buying_power import put_collateral_usd
from stockviz.services.trading.execute import NoFxRateError
from stockviz.services.trading.portfolio import signed_greeks
from stockviz.services.trading.views import greeks_out

router = APIRouter(prefix="/v1/options", tags=["options"])

SessionDep = Annotated[Session, Depends(get_session)]

_ZERO_GREEKS = OptionGreeksOut(delta=0.0, gamma=0.0, theta=0.0, vega=0.0, rho=0.0)
_VOL_METHOD = "historical volatility of daily closes, 30 sessions, annualised"


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
        volatility_method=_VOL_METHOD,
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
    body: OptionTradeIn, session: SessionDep, user_id: UserIdDep
) -> OptionTradeOut:
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
def list_options_positions(session: SessionDep, user_id: UserIdDep) -> list[OptionPositionOut]:
    """Return the user's open options positions, newest first, each priced now."""
    rows = list(
        session.exec(
            select(OptionsPosition)
            .where(
                OptionsPosition.user_id == user_id,
                OptionsPosition.status == OptionStatus.OPEN,
            )
            .order_by(OptionsPosition.opened_at.desc())  # type: ignore[attr-defined]
        )
    )
    return [_to_out(session, position) for position in rows]
