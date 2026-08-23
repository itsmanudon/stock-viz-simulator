"""`/v1/options/trade` and `/v1/options/positions` — options paper trading.

Long-only book: open a call/put (premium debited from portfolio cash), close
it back at theoretical value, or let the settlement job resolve it at expiry.
Both endpoints mutate per-user data so they depend on ``UserIdDep``.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select

from stockviz.auth import UserIdDep
from stockviz.db import get_session
from stockviz.models import OptionsPosition, OptionStatus, OptionType
from stockviz.models.option import CONTRACT_MULTIPLIER
from stockviz.schemas import (
    OptionGreeksOut,
    OptionPositionOut,
    OptionTradeIn,
    OptionTradeOut,
)
from stockviz.services.options import (
    InsufficientCashForOption,
    InvalidExpiry,
    NoOptionMarketData,
    OptionNotFound,
    OptionSymbolNotFound,
    OptionTradeError,
    close_option,
    open_option,
    value_option,
)
from stockviz.services.trading.execute import NoFxRateError

router = APIRouter(prefix="/v1/options", tags=["options"])

SessionDep = Annotated[Session, Depends(get_session)]

_ZERO_GREEKS = OptionGreeksOut(delta=0.0, gamma=0.0, theta=0.0, vega=0.0)


def _to_out(session: Session, position: OptionsPosition) -> OptionPositionOut:
    """Build the wire shape, valuing the position at the current Black-Scholes price."""
    try:
        price = value_option(session, position)
        current_value = (
            Decimal(str(price.value)) * CONTRACT_MULTIPLIER * position.quantity
        ).quantize(Decimal("0.01"))
        if current_value < 0:
            current_value = Decimal("0.00")
        greeks = OptionGreeksOut(
            delta=round(price.delta, 6),
            gamma=round(price.gamma, 6),
            theta=round(price.theta, 6),
            vega=round(price.vega, 6),
        )
    except NoOptionMarketData:
        current_value = Decimal("0.00")
        greeks = _ZERO_GREEKS

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
            )
        except OptionSymbolNotFound as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
        except (InsufficientCashForOption, NoOptionMarketData, NoFxRateError) as exc:
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
        except NoOptionMarketData as exc:
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
