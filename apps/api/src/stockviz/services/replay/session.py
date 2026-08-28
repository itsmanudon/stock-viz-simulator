"""ReplaySession lifecycle: create, next-bar advance, cancel, submit.

Market snapshots are built from stored ``PriceBar`` rows clipped to the
session's frozen range. Callers never supply OHLC. Live ``Trade`` /
``SimulatedExecution`` / outbox rows are never written.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlmodel import Session, select

from stockviz._time import utcnow
from stockviz.models import ReplayFill, ReplayPosition, ReplaySession, ReplaySessionStatus, Symbol
from stockviz.services.replay.errors import (
    ReplayClosed,
    ReplayCompleted,
    ReplayLookaheadError,
    ReplayNotFound,
    ReplayRangeError,
    ReplaySymbolNotFound,
    ReplayUnsupportedCurrency,
)
from stockviz.services.replay.ledger import apply_replay_fill, get_replay_position
from stockviz.services.replay.market import (
    count_replay_bars,
    get_next_session_bar,
    market_snapshot_for_replay,
    resolve_replay_end,
    resolve_replay_start,
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
MIN_REPLAY_BARS = 2


@dataclass(frozen=True, slots=True)
class ReplaySubmitResult:
    replay: ReplaySession
    decision: FillDecision
    fill: ReplayFill | None


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


def _complete(replay: ReplaySession) -> None:
    replay.status = ReplaySessionStatus.COMPLETED.value
    replay.completed_at = utcnow()
    _touch(replay)


def create_replay_session(
    session: Session,
    *,
    user_id: int,
    ticker: str,
    start_at: datetime,
    end_at: datetime | None = None,
    starting_cash: Decimal = DEFAULT_REPLAY_CASH,
) -> ReplaySession:
    """Open an isolated book over a frozen stored-1d range.

    Profile is pinned to ``LIVE_PAPER_EXECUTION_PROFILE`` (legacy_close v1).
    ``end_at`` is resolved once at creation; later PriceBar ingest cannot extend
    the horizon.
    """

    if starting_cash <= 0:
        raise ValueError("starting_cash must be greater than 0")
    ticker = ticker.strip().upper()
    symbol = session.get(Symbol, ticker)
    if symbol is None:
        raise ReplaySymbolNotFound(f"Symbol {ticker!r} not found")
    currency = symbol.currency or "USD"
    if currency != "USD":
        raise ReplayUnsupportedCurrency(
            f"Replay sessions are USD-only until historical FX exists; {ticker!r} is {currency}"
        )

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
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def advance_replay_session(session: Session, *, replay: ReplaySession) -> ReplaySession:
    """Move ``current_at`` to the next stored 1d bar inside the frozen range.

    Skips weekends/holidays by following stored bars. Completes the session
    when that bar is the last eligible bar (``end_at``).
    """

    if replay.id is None:
        raise ValueError("replay session must be persisted before advance")
    locked = lock_replay_session(session, session_id=replay.id, user_id=replay.user_id)
    _require_active(locked)
    nxt = get_next_session_bar(session, locked)
    if nxt is None:
        _complete(locked)
        session.add(locked)
        session.commit()
        session.refresh(locked)
        return locked
    clock = _clock_from_row(locked).advance_to(as_aware_utc(nxt.ts))
    locked.current_at = as_naive_utc(clock.instant())
    if get_next_session_bar(session, locked) is None:
        _complete(locked)
    else:
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
    locked.status = ReplaySessionStatus.CANCELLED.value
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
    """Evaluate against the server-selected current bar at ``current_at``.

    ``submitted_at`` is the session clock. FILLED mutates isolated cash only.
    """

    if replay.id is None:
        raise ValueError("replay session must be persisted before submit")
    locked = lock_replay_session(session, session_id=replay.id, user_id=replay.user_id)
    _require_active(locked)
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
        )
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
    "DEFAULT_REPLAY_CASH",
    "ReplaySubmitResult",
    "advance_replay_session",
    "cancel_replay_session",
    "create_replay_session",
    "get_replay_position",
    "get_replay_session",
    "list_replay_fills",
    "list_replay_positions",
    "list_replay_sessions",
    "lock_replay_session",
    "session_can_advance",
    "submit_replay_order",
]
