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

**Profiles (A6.9).** Under ``intrabar_ohlc`` a resting order is judged on the
bar's range with the open first (a gap fills at the open), not on its close.

**Brackets (A6.9, M9.4).** A long entry (market, or a buy limit) with a sell
stop and a sell target, one cancels the other. The entry is a ``bracket`` row;
the stop and the target are ``stop_loss`` and ``take_profit`` rows with
``parent_id`` = the entry, all three sharing ``oco_group``. The children are
``pending`` until the entry fills, then ``open`` from that bar and first judged
on the next one. An open pair goes through the kernel's ``evaluate_oco_exit``:
when both levels are inside one bar, the stored minutes inside it decide, and
without minutes the stop fills, labelled "order inside the bar unknown". When
one child fills, the other is cancelled. Cancelling an entry that has not
filled cancels its children; a child can be cancelled alone, and the other
then rests as a plain order.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

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
from stockviz.services.replay.intraday import DAILY, minutes_inside
from stockviz.services.replay.ledger import apply_replay_fill, get_replay_position
from stockviz.services.replay.market import ReplayBar, snapshot_from_bar
from stockviz.services.replay.timeutil import as_aware_utc
from stockviz.services.simulation import (
    INTRABAR_OHLC,
    FeeBreakdown,
    FillDecision,
    FillStatus,
    MarketSnapshot,
    OrderIntent,
    OrderSide,
    SimulationOrderType,
    evaluate_oco_exit,
    evaluate_order,
    get_execution_profile,
    get_fee_schedule,
)

BRACKET = "bracket"
ACTIVE_STATUSES = (ReplayOrderStatus.OPEN.value, ReplayOrderStatus.PENDING.value)
EntryType = Literal["market", "limit"]

EMPTY_FEES = FeeBreakdown(())


def require_tradable(replay: ReplaySession) -> None:
    """Index sessions are for watching (chart, indicators, drawings), not trading."""
    if is_index_ticker(replay.ticker):
        raise ReplayNotTradable(f"{replay.ticker} is an index: it can be replayed, not traded")


def replay_fee_date(replay: ReplaySession, ts: datetime):
    """The venue date of the bar a fill is at (daily bars carry their venue
    date; an intraday bar's open instant is read in the venue's zone)."""
    stamp = ts if replay.interval == DAILY else as_aware_utc(ts)
    return bar_date(stamp, venue_for_ticker(replay.ticker))


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
        # The DP charge is once per scrip per venue day: one bar a day for a
        # daily session, many for an intraday one.
        day = replay_fee_date(replay, at)
        sold = db.exec(
            select(ReplayFill.evaluated_at).where(
                ReplayFill.session_id == replay.id,
                ReplayFill.side == OrderSide.SELL.value,
            )
        ).all()
        dp_due = all(replay_fee_date(replay, ts) != day for ts in sold)
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


def active_replay_orders(db: Session, *, replay: ReplaySession) -> list[ReplayOrder]:
    """Open and pending (a bracket child waiting for its entry), oldest first."""
    assert replay.id is not None
    return list(
        db.exec(
            select(ReplayOrder)
            .where(
                ReplayOrder.session_id == replay.id,
                col(ReplayOrder.status).in_(ACTIVE_STATUSES),
            )
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
    dry_run: bool = False,
) -> ReplayOrder:
    """Stage a resting order at the session clock (``replay`` is locked). Does not commit.

    ``dry_run`` checks the order (price, side, cash or shares) and stages
    nothing: a bracket's limit entry is checked this way."""
    require_tradable(replay)
    if order_type is SimulationOrderType.MARKET:
        raise ReplayOrderError("Market orders fill at once; they do not rest")
    if not dry_run:
        require_room(db, replay, 1)
    if limit_price is None or limit_price <= 0:
        raise ReplayOrderError("A limit or stop order needs a positive price")
    if quantity <= 0:
        raise ReplayOrderError("quantity must be greater than 0")
    if order_type in (SimulationOrderType.STOP_LOSS, SimulationOrderType.TAKE_PROFIT) and (
        side is not OrderSide.SELL
    ):
        label = "Stop-loss" if order_type is SimulationOrderType.STOP_LOSS else "Take-profit"
        raise ReplayOrderError(f"{label} orders are sell-only")
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
    if not dry_run:
        db.add(row)
    return row


def require_room(db: Session, replay: ReplaySession, rows: int) -> None:
    if len(active_replay_orders(db, replay=replay)) + rows > MAX_OPEN_REPLAY_ORDERS:
        raise ReplayOrderError(f"At most {MAX_OPEN_REPLAY_ORDERS} open orders in a session")


def validate_bracket(
    *,
    quantity: Decimal,
    entry_type: EntryType,
    entry_price: Decimal | None,
    stop_price: Decimal | None,
    target_price: Decimal | None,
) -> tuple[Decimal, Decimal]:
    """(stop, target) for a long bracket, or :class:`ReplayOrderError`.

    ``entry_price`` is the limit of a limit entry, or the current close a
    market entry fills at: the stop must be below it and the target above."""
    if quantity <= 0:
        raise ReplayOrderError("quantity must be greater than 0")
    if stop_price is None or stop_price <= 0 or target_price is None or target_price <= 0:
        raise ReplayOrderError("A bracket needs a positive stop and a positive target")
    if entry_type == "limit" and (entry_price is None or entry_price <= 0):
        raise ReplayOrderError("A limit entry needs a positive limit price")
    if entry_price is not None and not (stop_price < entry_price < target_price):
        where = "limit" if entry_type == "limit" else "current close"
        raise ReplayOrderError(
            f"A bracket's stop must be below the {where} ({entry_price}) and its target above it"
        )
    return stop_price, target_price


def place_replay_bracket(
    db: Session,
    *,
    replay: ReplaySession,
    quantity: Decimal,
    entry_type: EntryType,
    entry_price: Decimal,
    stop_price: Decimal,
    target_price: Decimal,
    entry_fill: ReplayFill | None = None,
) -> tuple[ReplayOrder, ReplayOrder, ReplayOrder]:
    """Stage a bracket (``replay`` is locked): (entry, stop, target). Does not commit.

    A market entry has already filled (``entry_fill``, at ``entry_price``):
    the entry row is ``filled`` and the children ``open`` (first judged on the
    next bar). A limit entry rests ``open`` at ``entry_price`` and its
    children wait ``pending``."""
    require_tradable(replay)
    assert replay.id is not None
    now = utcnow()
    filled = entry_fill is not None
    entry = ReplayOrder(
        session_id=replay.id,
        ticker=replay.ticker,
        side=OrderSide.BUY.value,
        order_type=BRACKET,
        quantity=quantity,
        limit_price=entry_price,
        status=(ReplayOrderStatus.FILLED if filled else ReplayOrderStatus.OPEN).value,
        placed_at=replay.current_at,
        resolved_at=replay.current_at if filled else None,
        reason=(
            "Market entry filled at the current close; the stop and the target rest from the "
            "next bar"
            if filled
            else None
        ),
        created_at=now,
        updated_at=now,
    )
    db.add(entry)
    db.flush()
    assert entry.id is not None
    entry.oco_group = entry.id
    child_status = (ReplayOrderStatus.OPEN if filled else ReplayOrderStatus.PENDING).value
    children: list[ReplayOrder] = []
    for kind, price in (
        (SimulationOrderType.STOP_LOSS, stop_price),
        (SimulationOrderType.TAKE_PROFIT, target_price),
    ):
        child = ReplayOrder(
            session_id=replay.id,
            ticker=replay.ticker,
            side=OrderSide.SELL.value,
            order_type=kind.value,
            quantity=quantity,
            limit_price=price,
            status=child_status,
            placed_at=replay.current_at,
            parent_id=entry.id,
            oco_group=entry.id,
            created_at=now,
            updated_at=now,
        )
        db.add(child)
        children.append(child)
    if entry_fill is not None:
        entry_fill.order_id = entry.id
        db.add(entry_fill)
    db.add(entry)
    db.flush()
    return entry, children[0], children[1]


def _resolve(order: ReplayOrder, status: ReplayOrderStatus, at: datetime, reason: str) -> None:
    order.status = status.value
    order.resolved_at = at
    order.reason = reason
    order.updated_at = utcnow()


def _intent(order: ReplayOrder) -> OrderIntent:
    kind = (
        SimulationOrderType.LIMIT
        if order.order_type == BRACKET
        else SimulationOrderType(order.order_type)
    )
    return OrderIntent(
        ticker=order.ticker,
        side=OrderSide(order.side),
        order_type=kind,
        quantity=order.quantity,
        remaining_quantity=order.quantity,
        submitted_at=as_aware_utc(order.placed_at),
        limit_price=order.limit_price,
    )


class _Judge:
    """One advance's order evaluation: ``replay`` is locked, its clock is
    ``bar.ts``; stages fills and order changes, the caller commits."""

    def __init__(self, db: Session, replay: ReplaySession, bar: ReplayBar) -> None:
        self.db = db
        self.replay = replay
        self.bar = bar
        self.profile = get_execution_profile(replay.profile_name, replay.model_version)
        self.snapshot = snapshot_from_bar(bar, observed_at=replay.current_at)
        self.fills: list[ReplayFill] = []
        self.done: set[int] = set()

    def _book(self, order: ReplayOrder, decision: FillDecision) -> ReplayFill | None:
        """Book a filled decision for ``order``; a refusal rejects the order."""
        assert decision.fill_price is not None
        side = OrderSide(order.side)
        at = self.replay.current_at
        fees = replay_fill_fees(
            self.db,
            replay=self.replay,
            side=side,
            quantity=decision.fill_quantity,
            price=decision.fill_price,
            at=at,
        )
        try:
            # The ledger refuses before it changes anything, so a refusal
            # leaves cash and the position as they were.
            fill = apply_replay_fill(
                self.db,
                replay=self.replay,
                ticker=self.replay.ticker,
                side=side,
                quantity=decision.fill_quantity,
                decision=decision,
                market_interval=self.snapshot.interval,
                order_type=order.order_type,
                evaluated_at_naive=at,
                fees=fees,
                order_id=order.id,
            )
            self.db.flush()
        except (ReplayInsufficientCash, ReplayInsufficientPosition) as exc:
            _resolve(order, ReplayOrderStatus.REJECTED, at, str(exc))
            self.db.add(order)
            return None
        _resolve(order, ReplayOrderStatus.FILLED, at, decision.trace.reason)
        self.db.add(order)
        self.fills.append(fill)
        return fill

    def single(self, order: ReplayOrder) -> ReplayFill | None:
        decision = evaluate_order(_intent(order), self.snapshot, self.profile)
        if decision.status is FillStatus.INELIGIBLE:
            _resolve(
                order, ReplayOrderStatus.REJECTED, self.replay.current_at, decision.trace.reason
            )
            self.db.add(order)
            return None
        if decision.status is not FillStatus.FILLED or decision.fill_price is None:
            return None
        return self._book(order, decision)

    def entry(self, order: ReplayOrder, children: list[ReplayOrder]) -> None:
        """A bracket's limit entry: on a fill, its children start resting."""
        if self.single(order) is None or order.status != ReplayOrderStatus.FILLED.value:
            if order.status == ReplayOrderStatus.REJECTED.value:
                for child in children:
                    _resolve(child, ReplayOrderStatus.CANCELLED, self.replay.current_at,
                             "The bracket's entry was rejected")  # fmt: skip
                    self.db.add(child)
            return
        for child in children:
            if child.status != ReplayOrderStatus.PENDING.value:
                continue
            # Judged from the next bar: the order inside the entry's bar after
            # the fill is not known.
            child.status = ReplayOrderStatus.OPEN.value
            child.placed_at = self.replay.current_at
            child.updated_at = utcnow()
            self.db.add(child)
            self.done.add(child.id or 0)

    def _path(self) -> list[MarketSnapshot]:
        return minutes_inside(
            self.db,
            ticker=self.replay.ticker,
            interval=self.replay.interval,
            feed=self.replay.feed,
            bar_ts=self.bar.ts,
            closed_at=self.bar.closed_at,
        )

    def pair(self, stop: ReplayOrder, target: ReplayOrder) -> None:
        """An open stop and target of one bracket: one cancels the other."""
        result = evaluate_oco_exit(_intent(stop), _intent(target), self.snapshot, self.profile)
        if result.order_unknown and self.profile is INTRABAR_OHLC and self.replay.interval != "1m":
            path = self._path()
            if path:
                result = evaluate_oco_exit(
                    _intent(stop), _intent(target), self.snapshot, self.profile, path=path
                )
        decision = result.decision
        if decision.status is FillStatus.INELIGIBLE:
            for order in (stop, target):
                _resolve(order, ReplayOrderStatus.REJECTED, self.replay.current_at,
                         decision.trace.reason)  # fmt: skip
                self.db.add(order)
            return
        if result.leg is None or decision.status is not FillStatus.FILLED:
            return
        filled, other = (stop, target) if result.leg == "stop" else (target, stop)
        if self._book(filled, decision) is None:
            return
        word = "stop" if result.leg == "stop" else "target"
        _resolve(other, ReplayOrderStatus.CANCELLED, self.replay.current_at,
                 f"One cancels the other: the {word} filled")  # fmt: skip
        self.db.add(other)


def evaluate_open_orders(db: Session, *, replay: ReplaySession, bar: ReplayBar) -> list[ReplayFill]:
    """Judge every open order on ``bar`` (the bar the clock just reached).

    ``replay`` is locked and its clock is ``bar.ts``. Stages fills and order
    changes; the caller commits. Oldest first; a bracket's stop and target
    are judged together."""
    judge = _Judge(db, replay, bar)
    active = active_replay_orders(db, replay=replay)
    by_group: dict[int, list[ReplayOrder]] = {}
    for order in active:
        if order.parent_id is not None:
            by_group.setdefault(order.parent_id, []).append(order)
    for order in active:
        if order.id in judge.done or order.status != ReplayOrderStatus.OPEN.value:
            continue
        if order.placed_at >= replay.current_at:
            continue  # placed on this bar: first judged on the next one
        judge.done.add(order.id or 0)
        if order.order_type == BRACKET:
            judge.entry(order, by_group.get(order.id or 0, []))
            continue
        siblings = by_group.get(order.parent_id, []) if order.parent_id is not None else []
        pair = [
            o
            for o in siblings
            if o.id != order.id
            and o.status == ReplayOrderStatus.OPEN.value
            and o.placed_at < replay.current_at
        ]
        if pair:
            other = pair[0]
            judge.done.add(other.id or 0)
            stop, target = (
                (order, other) if order.order_type == SimulationOrderType.STOP_LOSS.value
                else (other, order)
            )  # fmt: skip
            judge.pair(stop, target)
            continue
        judge.single(order)
    return judge.fills


def close_open_orders(db: Session, *, replay: ReplaySession, status: ReplayOrderStatus) -> None:
    """Expire (session completed) or cancel (session cancelled) every open
    or pending order."""
    reason = (
        "The session completed with the order open"
        if status is ReplayOrderStatus.EXPIRED
        else "The session was cancelled"
    )
    for order in active_replay_orders(db, replay=replay):
        _resolve(order, status, replay.current_at, reason)
        db.add(order)


def cancel_replay_order(db: Session, *, replay: ReplaySession, order_id: int) -> ReplayOrder:
    """Cancel one open or pending order (``replay`` is locked and active). Commits.

    A bracket entry that has not filled takes its pending children with it."""
    order = db.get(ReplayOrder, order_id)
    if order is None or order.session_id != replay.id:
        raise ReplayOrderNotFound(f"Replay order {order_id} not found")
    if order.status not in ACTIVE_STATUSES:
        raise ReplayOrderError(f"Replay order {order_id} is {order.status}, not open")
    _resolve(order, ReplayOrderStatus.CANCELLED, replay.current_at, "Cancelled by you")
    db.add(order)
    if order.order_type == BRACKET:
        for child in db.exec(select(ReplayOrder).where(ReplayOrder.parent_id == order.id)).all():
            if child.status in ACTIVE_STATUSES:
                _resolve(child, ReplayOrderStatus.CANCELLED, replay.current_at,
                         "Its bracket entry was cancelled")  # fmt: skip
                db.add(child)
    db.commit()
    db.refresh(order)
    return order


__all__ = [
    "BRACKET",
    "active_replay_orders",
    "cancel_replay_order",
    "close_open_orders",
    "evaluate_open_orders",
    "list_replay_orders",
    "open_replay_orders",
    "place_replay_bracket",
    "place_replay_order",
    "replay_fee_date",
    "replay_fill_fees",
    "require_room",
    "require_tradable",
    "validate_bracket",
]
