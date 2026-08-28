"""Computed replay performance at the current observable bar.

Marks positions with the session's current stored close. Does not persist
equity, does not use live quotes, and never reads bars after ``current_at``.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlmodel import Session

from stockviz.models import ReplaySession
from stockviz.services.replay.ledger import MICROS
from stockviz.services.replay.market import (
    get_next_session_bar,
    get_session_bar,
    get_visible_replay_history,
)
from stockviz.services.replay.session import list_replay_fills, list_replay_positions

ZERO = Decimal("0")
PCT = Decimal("0.0001")


@dataclass(frozen=True, slots=True)
class ReplaySummary:
    cash: Decimal
    starting_cash: Decimal
    positions_market_value: Decimal
    equity: Decimal
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    total_pnl: Decimal
    return_pct: Decimal
    fills_count: int
    current_close: Decimal
    has_next: bool
    visible_high: Decimal
    visible_low: Decimal


def compute_replay_summary(session: Session, replay: ReplaySession) -> ReplaySummary:
    bar = get_session_bar(session, replay)
    close = bar.close
    positions = list_replay_positions(session, replay=replay)
    fills = list_replay_fills(session, replay=replay)
    visible = get_visible_replay_history(session, replay)

    market_value = ZERO
    unrealized = ZERO
    for pos in positions:
        market_value += (pos.quantity * close).quantize(MICROS)
        unrealized += ((close - pos.avg_cost) * pos.quantity).quantize(MICROS)

    realized = ZERO
    for fill in fills:
        if fill.realized_pnl is not None:
            realized += fill.realized_pnl

    cash = replay.cash_balance
    equity = (cash + market_value).quantize(MICROS)
    total_pnl = (equity - replay.starting_cash).quantize(MICROS)
    if replay.starting_cash > 0:
        return_pct = (total_pnl / replay.starting_cash * Decimal("100")).quantize(PCT)
    else:
        return_pct = ZERO

    highs = [row.high for row in visible] or [bar.high]
    lows = [row.low for row in visible] or [bar.low]

    return ReplaySummary(
        cash=cash,
        starting_cash=replay.starting_cash,
        positions_market_value=market_value.quantize(MICROS),
        equity=equity,
        realized_pnl=realized.quantize(MICROS),
        unrealized_pnl=unrealized.quantize(MICROS),
        total_pnl=total_pnl,
        return_pct=return_pct,
        fills_count=len(fills),
        current_close=close,
        has_next=get_next_session_bar(session, replay) is not None,
        visible_high=max(highs),
        visible_low=min(lows),
    )
