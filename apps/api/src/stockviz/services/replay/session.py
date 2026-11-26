"""ReplaySession lifecycle: create, next-bar advance, cancel, submit.

Market snapshots are built from stored ``PriceBar`` rows clipped to the
session's frozen range. Callers never supply OHLC. Live ``Trade`` /
``SimulatedExecution`` / outbox rows are never written.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from sqlmodel import Session, select

from stockviz._time import utcnow
from stockviz.models import (
    ReplayFill,
    ReplayOrder,
    ReplayOrderStatus,
    ReplayPosition,
    ReplaySession,
    ReplaySessionStatus,
    Symbol,
)
from stockviz.services.fee_view import resolve_fee_schedule
from stockviz.services.plans import end_session_plan
from stockviz.services.replay.errors import (
    ReplayClosed,
    ReplayCompleted,
    ReplayLagError,
    ReplayLookaheadError,
    ReplayNotFound,
    ReplayRangeError,
    ReplaySymbolNotFound,
)
from stockviz.services.replay.journal import freeze_replay_journal
from stockviz.services.replay.lag import end_inside_lag, lag_days_for, lag_waived_for
from stockviz.services.replay.ledger import apply_replay_fill, get_replay_position
from stockviz.services.replay.market import (
    count_replay_bars,
    get_next_session_bar,
    market_snapshot_for_replay,
    resolve_replay_end,
    resolve_replay_start,
)
from stockviz.services.replay.orders import (
    close_open_orders,
    evaluate_open_orders,
    place_replay_order,
    replay_fill_fees,
    require_tradable,
)
from stockviz.services.replay.timeutil import as_aware_utc, as_naive_utc
from stockviz.services.simulation import (
    LIVE_PAPER_EXECUTION_PROFILE,
    FillDecision,
    FillStatus,
    OrderIntent,
    OrderSide,
    SimulationClock,
    SimulationOrderType,
    evaluate_order,
    get_execution_profile,
)

DEFAULT_REPLAY_CASH = Decimal("100000.00")
DEFAULT_CASH_BY_CURRENCY: dict[str, Decimal] = {
    "USD": DEFAULT_REPLAY_CASH,
    "INR": Decimal("1000000.00"),  # ₹10 lakh
}
"""A4.6: starting cash when the request names none, in the session's
currency. Other currencies start with 100,000 units."""
MIN_REPLAY_BARS = 2


def default_starting_cash(currency: str) -> Decimal:
    return DEFAULT_CASH_BY_CURRENCY.get(currency, DEFAULT_REPLAY_CASH)


@dataclass(frozen=True, slots=True)
class ReplaySubmitResult:
    replay: ReplaySession
    decision: FillDecision | None
    """The kernel's decision for a market order; None for a resting order."""
    fill: ReplayFill | None
    order: ReplayOrder | None = None
    """A4.6: the resting limit / stop order placed (not yet judged)."""


def _clock_from_row(replay: ReplaySession) -> SimulationClock:
    return SimulationClock(now=as_aware_utc(replay.current_at))


def _touch(replay: ReplaySession) -> None:
    replay.updated_at = utcnow()


def _require_active(replay: ReplaySession) -> ReplaySession:
    if replay.status == ReplaySessionStatus.CANCELLED.value:
        raise ReplayClosed(f"Replay session {replay.id} is cancelled")
    if replay.status == ReplaySessionStatus.COMPLETED.value:
        raise ReplayCompleted(f"Replay session {replay.id} is completed")
    if replay.status != ReplaySessionStatus.ACTIVE.value:
        raise ReplayClosed(f"Replay session {replay.id} is not active")
    return replay


def lock_replay_session(session: Session, *, session_id: int, user_id: int) -> ReplaySession:
    """``SELECT ... FOR UPDATE`` the session row and return a fresh copy."""

    replay = get_replay_session(session, session_id=session_id, user_id=user_id)
    session.refresh(replay, with_for_update=True)
    return replay


def get_replay_session(session: Session, *, session_id: int, user_id: int) -> ReplaySession:
    row = session.get(ReplaySession, session_id)
    if row is None or row.user_id != user_id:
        raise ReplayNotFound(f"Replay session {session_id} not found")
    return row


def list_replay_sessions(session: Session, *, user_id: int) -> list[ReplaySession]:
    return list(
        session.exec(
            select(ReplaySession)
            .where(ReplaySession.user_id == user_id)
            .order_by(ReplaySession.id.desc())  # type: ignore[attr-defined]
        ).all()
    )


def session_can_advance(replay: ReplaySession) -> bool:
    """O(1) next-bar flag for list rows. True only while active and before end_at."""

    return replay.status == ReplaySessionStatus.ACTIVE.value and replay.current_at < replay.end_at


def list_replay_fills(session: Session, *, replay: ReplaySession) -> list[ReplayFill]:
    assert replay.id is not None
    return list(
        session.exec(
            select(ReplayFill)
            .where(ReplayFill.session_id == replay.id)
            .order_by(ReplayFill.id.asc())  # type: ignore[attr-defined]
        ).all()
    )


def list_replay_positions(session: Session, *, replay: ReplaySession) -> list[ReplayPosition]:
    assert replay.id is not None
    return list(
        session.exec(
            select(ReplayPosition)
            .where(ReplayPosition.session_id == replay.id)
            .order_by(ReplayPosition.ticker.asc())  # type: ignore[attr-defined]
        ).all()
    )


def _complete(session: Session, replay: ReplaySession) -> None:
    close_open_orders(session, replay=replay, status=ReplayOrderStatus.EXPIRED)
    replay.status = ReplaySessionStatus.COMPLETED.value
    replay.completed_at = utcnow()
    end_session_plan(session, replay=replay)
    _touch(replay)


def create_replay_session(
    session: Session,
    *,
    user_id: int,
    ticker: str,
    start_at: datetime,
    end_at: datetime | None = None,
    starting_cash: Decimal | None = None,
    today: date | None = None,
) -> ReplaySession:
    """Open an isolated book over a frozen stored-1d range.

    Profile is pinned to ``LIVE_PAPER_EXECUTION_PROFILE`` (legacy_close v1).
    ``end_at`` is resolved once at creation; later PriceBar ingest cannot extend
    the horizon.

    A4.6: the book is in the symbol's currency, with ``starting_cash`` in it
    (default ``default_starting_cash``); fills pay the venue's default fee
    schedule (``auto``). An Indian session must end ``REPLAY_MIN_LAG_DAYS``
    before ``today`` (the venue's date) unless the owner's override lists the
    user (``lag.py``).
    """

    ticker = ticker.strip().upper()
    symbol = session.get(Symbol, ticker)
    if symbol is None:
        raise ReplaySymbolNotFound(f"Symbol {ticker!r} not found")
    currency = (symbol.currency or "USD").upper()
    if starting_cash is None:
        starting_cash = default_starting_cash(currency)
    if starting_cash <= 0:
        raise ValueError("starting_cash must be greater than 0")

    start_bar = resolve_replay_start(session, ticker=ticker, requested=start_at)
    end_bar = resolve_replay_end(session, ticker=ticker, requested=end_at)
    if end_bar.ts < start_bar.ts:
        raise ReplayRangeError("Resolved replay end is before start")
    n_bars = count_replay_bars(session, ticker=ticker, start_ts=start_bar.ts, end_ts=end_bar.ts)
    if n_bars < MIN_REPLAY_BARS:
        raise ReplayRangeError(
            f"Replay range for {ticker!r} must contain at least {MIN_REPLAY_BARS} "
            f"stored 1d bars; resolved {n_bars}"
        )

    lag_override = False
    cutoff = end_inside_lag(ticker, end_bar.ts, today=today)
    if cutoff is not None:
        if not lag_waived_for(user_id):
            raise ReplayLagError(
                f"Indian replay sessions must end at least {lag_days_for(ticker)} days before "
                f"today: choose an end on or before {cutoff.isoformat()} "
                f"({ticker} would end {end_bar.ts.date().isoformat()})."
            )
        lag_override = True

    profile = get_execution_profile(
        LIVE_PAPER_EXECUTION_PROFILE.name, LIVE_PAPER_EXECUTION_PROFILE.model_version
    )
    now = utcnow()
    row = ReplaySession(
        user_id=user_id,
        ticker=ticker,
        profile_name=profile.name,
        model_version=profile.model_version,
        start_at=start_bar.ts,
        current_at=start_bar.ts,
        end_at=end_bar.ts,
        starting_cash=starting_cash,
        cash_balance=starting_cash,
        status=ReplaySessionStatus.ACTIVE.value,
        currency=currency,
        fee_schedule=resolve_fee_schedule("auto", ticker),
        lag_override=lag_override,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def advance_replay_session(
    session: Session,
    *,
    replay: ReplaySession,
    expected_current_at: datetime | None = None,
) -> ReplaySession:
    """Move ``current_at`` to the next stored 1d bar inside the frozen range.

    Audit SR-10 (Phase 5.1):

    - ``expected_current_at`` is the bar the caller saw. If the session has
      already moved on (a repeated or doubled request), nothing changes and
      the current state is returned, so two clicks move one bar.
    - Reaching the last bar no longer completes the session: that bar can be
      traded. Advancing from the last bar completes it.

    Replay follows stored daily bars; it does not apply an exchange calendar.
    """

    if replay.id is None:
        raise ValueError("replay session must be persisted before advance")
    locked = lock_replay_session(session, session_id=replay.id, user_id=replay.user_id)
    if expected_current_at is not None and as_naive_utc(expected_current_at) != locked.current_at:
        session.commit()  # release the row lock
        return locked
    _require_active(locked)
    nxt = get_next_session_bar(session, locked)
    if nxt is None:
        _complete(session, locked)
        session.add(locked)
        session.commit()
        session.refresh(locked)
        return locked
    clock = _clock_from_row(locked).advance_to(as_aware_utc(nxt.ts))
    locked.current_at = as_naive_utc(clock.instant())
    # A4.6: resting orders are judged on the bar the clock just reached.
    fills = evaluate_open_orders(session, replay=locked, bar=nxt)
    if fills:
        freeze_replay_journal(session, replay=locked, locked_at=locked.current_at)
    _touch(locked)
    session.add(locked)
    session.commit()
    session.refresh(locked)
    return locked


def cancel_replay_session(session: Session, *, replay: ReplaySession) -> ReplaySession:
    if replay.id is None:
        raise ValueError("replay session must be persisted before cancel")
    locked = lock_replay_session(session, session_id=replay.id, user_id=replay.user_id)
    if locked.status == ReplaySessionStatus.COMPLETED.value:
        raise ReplayCompleted(f"Replay session {locked.id} is completed")
    if locked.status == ReplaySessionStatus.CANCELLED.value:
        return locked
    close_open_orders(session, replay=locked, status=ReplayOrderStatus.CANCELLED)
    locked.status = ReplaySessionStatus.CANCELLED.value
    end_session_plan(session, replay=locked)
    _touch(locked)
    session.add(locked)
    session.commit()
    session.refresh(locked)
    return locked


def submit_replay_order(
    session: Session,
    *,
    replay: ReplaySession,
    side: OrderSide,
    order_type: SimulationOrderType,
    quantity: Decimal,
    limit_price: Decimal | None = None,
) -> ReplaySubmitResult:
    """A market order: evaluate against the server-selected current bar at
    ``current_at``. A4.6: a limit / stop-loss / take-profit order rests
    (``orders.place_replay_order``) and is judged from the next bar on.

    ``submitted_at`` is the session clock. FILLED mutates isolated cash only.
    """

    if replay.id is None:
        raise ValueError("replay session must be persisted before submit")
    locked = lock_replay_session(session, session_id=replay.id, user_id=replay.user_id)
    _require_active(locked)
    require_tradable(locked)
    if order_type is not SimulationOrderType.MARKET:
        try:
            order = place_replay_order(
                session,
                replay=locked,
                side=side,
                order_type=order_type,
                quantity=quantity,
                limit_price=limit_price,
            )
        except Exception:
            session.rollback()
            raise
        _touch(locked)
        session.add(locked)
        session.commit()
        session.refresh(order)
        session.refresh(locked)
        return ReplaySubmitResult(replay=locked, decision=None, fill=None, order=order)
    clock = _clock_from_row(locked)
    snapshot = market_snapshot_for_replay(session, locked)
    if not clock.permits(snapshot.observed_at):
        raise ReplayLookaheadError(
            "snapshot observed_at is after the simulation clock "
            f"({snapshot.observed_at.isoformat()} > {clock.instant().isoformat()})"
        )
    submitted = clock.instant()
    profile = get_execution_profile(locked.profile_name, locked.model_version)
    intent = OrderIntent(
        ticker=locked.ticker,
        side=side,
        order_type=order_type,
        quantity=quantity,
        remaining_quantity=quantity,
        submitted_at=submitted,
        limit_price=limit_price,
    )
    decision = evaluate_order(intent, snapshot, profile)
    fill: ReplayFill | None = None
    if decision.status is FillStatus.FILLED:
        assert decision.fill_price is not None
        fees = replay_fill_fees(
            session,
            replay=locked,
            side=side,
            quantity=decision.fill_quantity,
            price=decision.fill_price,
            at=locked.current_at,
        )
        fill = apply_replay_fill(
            session,
            replay=locked,
            ticker=locked.ticker,
            side=side,
            quantity=quantity,
            decision=decision,
            market_interval=snapshot.interval,
            order_type=order_type.value,
            evaluated_at_naive=as_naive_utc(clock.instant()),
            fees=fees,
        )
        freeze_replay_journal(session, replay=locked, locked_at=as_naive_utc(clock.instant()))
        _touch(locked)
        session.add(locked)
        session.commit()
        session.refresh(locked)
        if fill.id is None:
            session.refresh(fill)
    else:
        session.commit()

    return ReplaySubmitResult(replay=locked, decision=decision, fill=fill)


__all__ = [
    "DEFAULT_CASH_BY_CURRENCY",
    "DEFAULT_REPLAY_CASH",
    "ReplaySubmitResult",
    "advance_replay_session",
    "cancel_replay_session",
    "create_replay_session",
    "default_starting_cash",
    "get_replay_position",
    "get_replay_session",
    "list_replay_fills",
    "list_replay_positions",
    "list_replay_sessions",
    "lock_replay_session",
    "session_can_advance",
    "submit_replay_order",
]
