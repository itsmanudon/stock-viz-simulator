"""Fee schedules (A4.2, M7.2). Public, 60/min.

``GET /v1/fees/schedules`` lists every family with its versions, each
component's rate and the document it was copied from, the brokerage models
and which schedule each venue gets by default. ``GET /v1/fees/estimate``
prices one order with the ticker's default schedule (the one a live paper
fill pays): the order review shows it before the order is placed. ``price``
defaults to the latest close; ``on`` to today's date on the ticker's venue.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlmodel import Session

from stockviz._time import utcnow
from stockviz.db import get_session
from stockviz.limiter import limiter
from stockviz.models import Symbol
from stockviz.schemas import FeeEstimateLineOut, FeeEstimateOut, FeeSchedulesOut
from stockviz.services.fee_view import (
    brokerage_out,
    default_schedule_name,
    fee_date,
    schedules_out,
    source_out,
)
from stockviz.services.simulation import OrderSide, get_fee_schedule
from stockviz.services.trading.execute import latest_bar

router = APIRouter(prefix="/v1/fees", tags=["fees"])

SessionDep = Annotated[Session, Depends(get_session)]

DP_NOTE = (
    "The DP charge is per scrip per day: a second sell of the same stock on the same day "
    "does not pay it again."
)


@router.get("/schedules", response_model=FeeSchedulesOut)
@limiter.limit("60/minute")
def list_schedules(request: Request) -> FeeSchedulesOut:
    return schedules_out()


@router.get("/estimate", response_model=FeeEstimateOut)
@limiter.limit("60/minute")
def estimate(
    request: Request,
    session: SessionDep,
    ticker: Annotated[str, Query(min_length=1, max_length=16)],
    side: Annotated[Literal["buy", "sell"], Query()],
    quantity: Annotated[Decimal, Query(gt=0, le=1_000_000_000)],
    price: Annotated[Decimal | None, Query(gt=0, le=1_000_000_000)] = None,
    on: Annotated[date | None, Query()] = None,
) -> FeeEstimateOut:
    ticker = ticker.upper()
    symbol = session.get(Symbol, ticker)
    if symbol is None:
        raise HTTPException(status_code=404, detail=f"Symbol {ticker!r} not found")
    if price is None:
        bar = latest_bar(session, ticker)
        if bar is None:
            raise HTTPException(status_code=422, detail=f"No stored close for {ticker}")
        price = bar.close
    day = on or fee_date(ticker, utcnow())
    name = default_schedule_name(ticker)
    schedule = get_fee_schedule(name)
    fees = schedule.fees(OrderSide(side), quantity, price, on=day)
    notional = price * quantity
    total = fees.total
    lines = []
    for line in fees.lines:
        comp = line.component
        if comp is not None:
            lines.append(
                FeeEstimateLineOut(
                    key=line.key, label=comp.label, amount=line.amount,
                    rate_text=comp.rate_text(), source=source_out(comp.source),
                )
            )  # fmt: skip
        else:
            model = fees.brokerage
            lines.append(
                FeeEstimateLineOut(
                    key=line.key,
                    label=model.label if model else "Brokerage",
                    amount=line.amount,
                    rate_text=model.rate_text() if model else "",
                    source=source_out(model.source) if model and model.source else None,
                )
            )
    has_dp = any(line.key == "dp_charge" for line in fees.lines)
    return FeeEstimateOut(
        ticker=ticker,
        side=side,
        quantity=quantity,
        price=price,
        currency=symbol.currency or "USD",
        schedule=schedule.name,
        label=schedule.label or schedule.name,
        on=day,
        effective_from=fees.version.effective_from if fees.version else None,
        before_coverage=fees.before_coverage,
        brokerage=brokerage_out(fees.brokerage) if fees.brokerage else None,
        notional=notional,
        total=total,
        net_amount=notional + total if side == "buy" else notional - total,
        lines=lines,
        dp_note=DP_NOTE if has_dp else None,
    )
