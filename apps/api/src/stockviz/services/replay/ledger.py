"""Isolated USD cash/position mutations for a ReplaySession.

This is not ``apply_fill``: it does not touch ``Portfolio`` / ``Trade``,
convert FX or enqueue Kafka. Since Phase 5.1 the arithmetic is the shared
``SimLedger`` (the backtester's too), which matches ``apply_fill``; this
module only loads the session's cash and position into it and writes them
back.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlmodel import Session, select

from stockviz.models import ReplayFill, ReplayPosition, ReplaySession
from stockviz.services.replay.errors import ReplayInsufficientCash, ReplayInsufficientPosition
from stockviz.services.simulation import (
    FillDecision,
    FillStatus,
    OrderSide,
    SimInsufficientCash,
    SimInsufficientPosition,
    SimLedger,
    SimPosition,
)

MICROS = Decimal("0.000001")


def get_replay_position(session: Session, *, session_id: int, ticker: str) -> ReplayPosition | None:
    return session.exec(
        select(ReplayPosition)
        .where(
            ReplayPosition.session_id == session_id,
            ReplayPosition.ticker == ticker,
        )
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
    ticker = ticker.upper()
    session_id = replay.id
    position = get_replay_position(db, session_id=session_id, ticker=ticker)

    ledger = SimLedger(cash=replay.cash_balance)
    if position is not None:
        ledger.positions[ticker] = SimPosition(position.quantity, position.avg_cost)
    try:
        fill = ledger.apply(side, ticker, quantity, price)
    except SimInsufficientCash as exc:
        raise ReplayInsufficientCash(
            f"Replay cash ${replay.cash_balance:.2f}; order requires ${(price * quantity):.2f}."
        ) from exc
    except SimInsufficientPosition as exc:
        held = position.quantity if position is not None else Decimal(0)
        raise ReplayInsufficientPosition(
            f"Replay position {held} {ticker}; order requires {quantity}."
        ) from exc

    realized_pnl = fill.realized_pnl
    replay.cash_balance = ledger.cash
    after = ledger.positions.get(ticker)
    if after is None:
        if position is not None:
            db.delete(position)
    elif position is None:
        db.add(
            ReplayPosition(
                session_id=session_id,
                ticker=ticker,
                quantity=after.quantity,
                avg_cost=after.avg_cost,
            )
        )
    else:
        position.quantity = after.quantity.quantize(MICROS)
        position.avg_cost = after.avg_cost
        db.add(position)

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
