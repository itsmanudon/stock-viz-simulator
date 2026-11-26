"""Replay fees and resting orders (A4.6, M9.2).

**Fees.** Every replay fill pays the session's ``fee_schedule`` (the A4.2
default resolver ``auto``, frozen at creation: an NSE or BSE symbol's equity
delivery schedule, ``none`` elsewhere), the version in force on the fill's
venue date (the bar's date), the Zerodha brokerage model (free for
delivery), and the DP charge once per scrip per venue day: on the first sell
at that bar. The same rules as live ``execute.fill_fees`` and backtest
``fills.book``, so the three agree to the cent (``tests/test_kernel_three_way.py``).

**Resting orders.** ``limit`` (buy or sell), ``stop_loss`` and
``take_profit`` (sell only, as the kernel rules). An order placed at the
session clock is first judged on the *next* bar: the trader placed it after
seeing this bar's close, which a market order would take. On every advance
each open order, oldest first, goes through ``evaluate_order`` with the
session's profile (``legacy_close``: triggers on that bar's close and fills
at it). Nothing is reserved; a fill the book cannot pay or deliver is
``rejected`` with the reason, never retried. Completing the session expires
the open orders; cancelling it cancels them.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlmodel import Session, col, select

from stockviz._time import utcnow
from stockviz.models import (
    ReplayFill,
    ReplayOrder,
    ReplayOrderStatus,
    ReplaySession,
)
from stockviz.models.replay import MAX_OPEN_REPLAY_ORDERS
from stockviz.services.bars.resample import bar_date
from stockviz.services.instruments import is_index_ticker
from stockviz.services.markets.calendar import venue_for_ticker
from stockviz.services.replay.errors import (
    ReplayInsufficientCash,
    ReplayInsufficientPosition,
    ReplayNotTradable,
    ReplayOrderError,
    ReplayOrderNotFound,
)
from stockviz.services.replay.ledger import apply_replay_fill, get_replay_position
from stockviz.services.replay.market import snapshot_from_bar
from stockviz.services.replay.timeutil import as_aware_utc
from stockviz.services.simulation import (
    FeeBreakdown,
    FillStatus,
    OrderIntent,
    OrderSide,
    SimulationOrderType,
    evaluate_order,
    get_execution_profile,
    get_fee_schedule,
)

EMPTY_FEES = FeeBreakdown(())


def require_tradable(replay: ReplaySession) -> None:
    """Index sessions are for watching (chart, indicators, drawings), not trading."""
    if is_index_ticker(replay.ticker):
        raise ReplayNotTradable(f"{replay.ticker} is an index: it can be replayed, not traded")


def replay_fee_date(replay: ReplaySession, ts: datetime):
    """The venue date of the bar a fill is at (bars carry their venue date)."""
    return bar_date(ts, venue_for_ticker(replay.ticker))


def replay_fill_fees(
    db: Session,
    *,
    replay: ReplaySession,
    side: OrderSide,
    quantity: Decimal,
    price: Decimal,
    at: datetime,
) -> FeeBreakdown:
    """The session schedule's fees for a fill at bar ``at`` (naive UTC)."""
    schedule = get_fee_schedule(replay.fee_schedule)
    if not schedule.versions:
        return EMPTY_FEES
    dp_due = True
    if side is OrderSide.SELL:
        assert replay.id is not None
        earlier = db.exec(
            select(ReplayFill.id).where(
                ReplayFill.session_id == replay.id,
                ReplayFill.side == OrderSide.SELL.value,
                ReplayFill.evaluated_at == at,
            )
        ).first()
        dp_due = earlier is None
    return schedule.fees(side, quantity, price, on=replay_fee_date(replay, at), dp_due=dp_due)


def list_replay_orders(db: Session, *, replay: ReplaySession) -> list[ReplayOrder]:
    assert replay.id is not None
    return list(
        db.exec(
            select(ReplayOrder)
            .where(ReplayOrder.session_id == replay.id)
            .order_by(col(ReplayOrder.id))
        ).all()
    )


def open_replay_orders(db: Session, *, replay: ReplaySession) -> list[ReplayOrder]:
    assert replay.id is not None
    return list(
        db.exec(
            select(ReplayOrder)
            .where(
                ReplayOrder.session_id == replay.id,
                ReplayOrder.status == ReplayOrderStatus.OPEN.value,
            )
            .order_by(col(ReplayOrder.id))
        ).all()
    )


def place_replay_order(
    db: Session,
    *,
    replay: ReplaySession,
    side: OrderSide,
    order_type: SimulationOrderType,
    quantity: Decimal,
    limit_price: Decimal | None,
) -> ReplayOrder:
    """Stage a resting order at the session clock (``replay`` is locked). Does not commit."""
    require_tradable(replay)
    if order_type is SimulationOrderType.MARKET:
        raise ReplayOrderError("Market orders fill at once; they do not rest")
    if limit_price is None or limit_price <= 0:
        raise ReplayOrderError("A limit or stop order needs a positive price")
    if quantity <= 0:
        raise ReplayOrderError("quantity must be greater than 0")
    if order_type in (SimulationOrderType.STOP_LOSS, SimulationOrderType.TAKE_PROFIT) and (
        side is not OrderSide.SELL
    ):
        label = "Stop-loss" if order_type is SimulationOrderType.STOP_LOSS else "Take-profit"
        raise ReplayOrderError(f"{label} orders are sell-only")
    if len(open_replay_orders(db, replay=replay)) >= MAX_OPEN_REPLAY_ORDERS:
        raise ReplayOrderError(f"At most {MAX_OPEN_REPLAY_ORDERS} open orders in a session")
    assert replay.id is not None
    if side is OrderSide.SELL:
        position = get_replay_position(db, session_id=replay.id, ticker=replay.ticker)
        held = position.quantity if position is not None else Decimal(0)
        if held < quantity:
            raise ReplayInsufficientPosition(
                f"Replay position {held} {replay.ticker}; order requires {quantity}."
            )
    elif (limit_price * quantity) > replay.cash_balance:
        raise ReplayInsufficientCash(
            f"Replay cash {replay.cash_balance:.2f} {replay.currency}; the order needs "
            f"{(limit_price * quantity):.2f} {replay.currency} at its limit."
        )
    now = utcnow()
    row = ReplayOrder(
        session_id=replay.id,
        ticker=replay.ticker,
        side=side.value,
        order_type=order_type.value,
        quantity=quantity,
        limit_price=limit_price,
        status=ReplayOrderStatus.OPEN.value,
        placed_at=replay.current_at,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    return row


def _resolve(order: ReplayOrder, status: ReplayOrderStatus, at: datetime, reason: str) -> None:
    order.status = status.value
    order.resolved_at = at
    order.reason = reason
    order.updated_at = utcnow()


def evaluate_open_orders(db: Session, *, replay: ReplaySession, bar) -> list[ReplayFill]:
    """Judge every open order on ``bar`` (the bar the clock just reached).

    ``replay`` is locked and its clock is ``bar.ts``. Stages fills and order
    changes; the caller commits."""
    fills: list[ReplayFill] = []
    profile = get_execution_profile(replay.profile_name, replay.model_version)
    snapshot = snapshot_from_bar(bar, observed_at=replay.current_at)
    for order in open_replay_orders(db, replay=replay):
        if order.placed_at >= replay.current_at:
            continue  # placed on this bar: first judged on the next one
        side = OrderSide(order.side)
        intent = OrderIntent(
            ticker=order.ticker,
            side=side,
            order_type=SimulationOrderType(order.order_type),
            quantity=order.quantity,
            remaining_quantity=order.quantity,
            submitted_at=as_aware_utc(order.placed_at),
            limit_price=order.limit_price,
        )
        decision = evaluate_order(intent, snapshot, profile)
        if decision.status is FillStatus.INELIGIBLE:
            _resolve(order, ReplayOrderStatus.REJECTED, replay.current_at, decision.trace.reason)
            db.add(order)
            continue
        if decision.status is not FillStatus.FILLED or decision.fill_price is None:
            continue
        fees = replay_fill_fees(
            db,
            replay=replay,
            side=side,
            quantity=decision.fill_quantity,
            price=decision.fill_price,
            at=replay.current_at,
        )
        try:
            # The ledger refuses before it changes anything, so a refusal
            # leaves cash and the position as they were.
            fill = apply_replay_fill(
                db,
                replay=replay,
                ticker=replay.ticker,
                side=side,
                quantity=decision.fill_quantity,
                decision=decision,
                market_interval=snapshot.interval,
                order_type=order.order_type,
                evaluated_at_naive=replay.current_at,
                fees=fees,
                order_id=order.id,
            )
            db.flush()
        except (ReplayInsufficientCash, ReplayInsufficientPosition) as exc:
            _resolve(order, ReplayOrderStatus.REJECTED, replay.current_at, str(exc))
            db.add(order)
            continue
        _resolve(order, ReplayOrderStatus.FILLED, replay.current_at, decision.trace.reason)
        db.add(order)
        fills.append(fill)
    return fills


def close_open_orders(db: Session, *, replay: ReplaySession, status: ReplayOrderStatus) -> None:
    """Expire (session completed) or cancel (session cancelled) every open order."""
    reason = (
        "The session completed with the order open"
        if status is ReplayOrderStatus.EXPIRED
        else "The session was cancelled"
    )
    for order in open_replay_orders(db, replay=replay):
        _resolve(order, status, replay.current_at, reason)
        db.add(order)


def cancel_replay_order(db: Session, *, replay: ReplaySession, order_id: int) -> ReplayOrder:
    """Cancel one open order (``replay`` is locked and active). Commits."""
    order = db.get(ReplayOrder, order_id)
    if order is None or order.session_id != replay.id:
        raise ReplayOrderNotFound(f"Replay order {order_id} not found")
    if order.status != ReplayOrderStatus.OPEN.value:
        raise ReplayOrderError(f"Replay order {order_id} is {order.status}, not open")
    _resolve(order, ReplayOrderStatus.CANCELLED, replay.current_at, "Cancelled by you")
    db.add(order)
    db.commit()
    db.refresh(order)
    return order


__all__ = [
    "cancel_replay_order",
    "close_open_orders",
    "evaluate_open_orders",
    "list_replay_orders",
    "open_replay_orders",
    "place_replay_order",
    "replay_fee_date",
    "replay_fill_fees",
    "require_tradable",
]
