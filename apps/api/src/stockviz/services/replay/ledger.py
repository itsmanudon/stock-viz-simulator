"""Isolated USD cash/position mutations for a ReplaySession.

This is not ``apply_fill``. It does not touch ``Portfolio`` / ``Trade``,
does not convert FX, and does not enqueue Kafka.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlmodel import Session, select

from stockviz.models import ReplayFill, ReplayPosition, ReplaySession
from stockviz.services.replay.errors import ReplayInsufficientCash, ReplayInsufficientPosition
from stockviz.services.simulation import FillDecision, FillStatus, OrderSide

MICROS = Decimal("0.000001")


def get_replay_position(session: Session, *, session_id: int, ticker: str) -> ReplayPosition | None:
    return session.exec(
        select(ReplayPosition)
        .where(ReplayPosition.session_id == session_id, ReplayPosition.ticker == ticker)
        .limit(1)
    ).first()


def apply_replay_fill(
    db: Session,
    *,
    replay: ReplaySession,
    ticker: str,
    side: OrderSide,
    quantity: Decimal,
    decision: FillDecision,
    market_interval: str,
    order_type: str,
    evaluated_at_naive: datetime,
) -> ReplayFill:
    """Debit/credit isolated cash and stage a ``ReplayFill``. Does not commit."""

    if replay.id is None:
        raise ValueError("replay session must be flushed before a fill is recorded")
    if decision.status is not FillStatus.FILLED or decision.fill_price is None:
        raise ValueError("replay fills are only recorded for filled decisions")

    price = decision.fill_price
    cost = (price * quantity).quantize(MICROS)
    realized_pnl: Decimal | None = None
    ticker = ticker.upper()
    session_id = replay.id
    position = get_replay_position(db, session_id=session_id, ticker=ticker)

    if side is OrderSide.BUY:
        if replay.cash_balance < cost:
            raise ReplayInsufficientCash(
                f"Replay cash ${replay.cash_balance:.2f}; order requires ${cost:.2f}."
            )
        replay.cash_balance = (replay.cash_balance - cost).quantize(MICROS)
        if position is None:
            db.add(
                ReplayPosition(
                    session_id=session_id,
                    ticker=ticker,
                    quantity=quantity,
                    avg_cost=price,
                )
            )
        else:
            total_qty = position.quantity + quantity
            position.avg_cost = (
                ((position.avg_cost * position.quantity) + (price * quantity)) / total_qty
            ).quantize(MICROS)
            position.quantity = total_qty.quantize(MICROS)
            db.add(position)
    elif side is OrderSide.SELL:
        held = position.quantity if position is not None else Decimal(0)
        if position is None or held < quantity:
            raise ReplayInsufficientPosition(
                f"Replay position {held} {ticker}; order requires {quantity}."
            )
        realized_pnl = ((price - position.avg_cost) * quantity).quantize(MICROS)
        replay.cash_balance = (replay.cash_balance + cost).quantize(MICROS)
        remaining = (position.quantity - quantity).quantize(MICROS)
        if remaining == 0:
            db.delete(position)
        else:
            position.quantity = remaining
            db.add(position)
    else:  # pragma: no cover
        raise ValueError(f"unsupported side {side!r}")

    db.add(replay)
    trace = decision.trace
    row = ReplayFill(
        session_id=session_id,
        ticker=ticker,
        side=side.value,
        quantity=quantity,
        fill_price=price,
        realized_pnl=realized_pnl,
        profile_name=trace.profile,
        model_version=trace.model_version,
        reference_price=trace.reference_price,
        reason=trace.reason,
        assumptions=list(trace.assumptions),
        market_interval=market_interval,
        order_type=order_type,
        evaluated_at=evaluated_at_naive,
    )
    db.add(row)
    return row
