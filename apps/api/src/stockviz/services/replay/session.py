"""ReplaySession lifecycle: create, clock, close, submit.

Evaluation uses the session's ``SimulationClock`` and ``evaluate_order``.
Callers supply the market snapshot; this module does not load ``PriceBar``
rows. Walking stored history without lookahead is SIM-06.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlmodel import Session, select

from stockviz._time import utcnow
from stockviz.models import ReplayFill, ReplayPosition, ReplaySession, ReplaySessionStatus
from stockviz.services.replay.errors import (
    ReplayClosed,
    ReplayLookaheadError,
    ReplayNotFound,
)
from stockviz.services.replay.ledger import apply_replay_fill, get_replay_position
from stockviz.services.replay.timeutil import as_aware_utc, as_naive_utc
from stockviz.services.simulation import (
    FillDecision,
    FillStatus,
    MarketSnapshot,
    OrderIntent,
    OrderSide,
    SimulationClock,
    SimulationOrderType,
    evaluate_order,
    get_execution_profile,
)

DEFAULT_REPLAY_CASH = Decimal("100000.00")


@dataclass(frozen=True, slots=True)
class ReplaySubmitResult:
    replay: ReplaySession
    decision: FillDecision
    fill: ReplayFill | None


def _clock_from_row(replay: ReplaySession) -> SimulationClock:
    return SimulationClock(now=as_aware_utc(replay.clock_now))


def _touch(replay: ReplaySession) -> None:
    replay.updated_at = utcnow()


def _require_open(replay: ReplaySession) -> ReplaySession:
    if replay.status != ReplaySessionStatus.OPEN.value:
        raise ReplayClosed(f"Replay session {replay.id} is closed")
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


def create_replay_session(
    session: Session,
    *,
    user_id: int,
    clock_now: datetime,
    starting_cash: Decimal = DEFAULT_REPLAY_CASH,
    profile_name: str = "legacy_close",
    model_version: str = "v1",
) -> ReplaySession:
    """Open an isolated book pinned to a registered execution profile."""

    if starting_cash <= 0:
        raise ValueError("starting_cash must be greater than 0")
    profile = get_execution_profile(profile_name, model_version)
    clock = SimulationClock(now=as_aware_utc(clock_now))
    now = utcnow()
    row = ReplaySession(
        user_id=user_id,
        profile_name=profile.name,
        model_version=profile.model_version,
        clock_now=as_naive_utc(clock.instant()),
        starting_cash=starting_cash,
        cash_balance=starting_cash,
        status=ReplaySessionStatus.OPEN.value,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def advance_replay_clock(
    session: Session,
    *,
    replay: ReplaySession,
    instant: datetime,
) -> ReplaySession:
    """Move the session clock forward. Does not evaluate orders or load bars."""

    _require_open(replay)
    clock = _clock_from_row(replay).advance_to(as_aware_utc(instant))
    replay.clock_now = as_naive_utc(clock.instant())
    _touch(replay)
    session.add(replay)
    session.commit()
    session.refresh(replay)
    return replay


def close_replay_session(session: Session, *, replay: ReplaySession) -> ReplaySession:
    if replay.status == ReplaySessionStatus.CLOSED.value:
        return replay
    replay.status = ReplaySessionStatus.CLOSED.value
    _touch(replay)
    session.add(replay)
    session.commit()
    session.refresh(replay)
    return replay


def market_snapshot_for_session(
    replay: ReplaySession,
    *,
    ticker: str,
    interval: str,
    open: Decimal,
    high: Decimal,
    low: Decimal,
    close: Decimal,
    volume: Decimal,
    observed_at: datetime | None = None,
) -> MarketSnapshot:
    """Build a kernel snapshot. Default ``observed_at`` is the session clock.

    Passing a future ``observed_at`` is allowed here; ``submit_replay_order``
    rejects it as lookahead. This helper does not load ``PriceBar`` rows.
    """

    clock = _clock_from_row(replay)
    observed = clock.instant() if observed_at is None else as_aware_utc(observed_at)
    return MarketSnapshot(
        ticker=ticker,
        observed_at=observed,
        interval=interval,
        open=open,
        high=high,
        low=low,
        close=close,
        volume=volume,
    )


def submit_replay_order(
    session: Session,
    *,
    replay: ReplaySession,
    ticker: str,
    side: OrderSide,
    order_type: SimulationOrderType,
    quantity: Decimal,
    snapshot: MarketSnapshot,
    limit_price: Decimal | None = None,
    submitted_at: datetime | None = None,
) -> ReplaySubmitResult:
    """Evaluate ``order`` against a caller-supplied snapshot at the session clock.

    FILLED decisions mutate isolated cash/positions and persist a ``ReplayFill``.
    NOT_TRIGGERED / INELIGIBLE do not. Live ``Trade`` / ``SimulatedExecution`` /
    outbox rows are never written.
    """

    _require_open(replay)
    clock = _clock_from_row(replay)
    ticker = ticker.strip().upper()
    if snapshot.ticker.upper() != ticker:
        raise ValueError(
            f"snapshot ticker {snapshot.ticker!r} does not match order ticker {ticker!r}"
        )

    if not clock.permits(snapshot.observed_at):
        raise ReplayLookaheadError(
            "snapshot observed_at is after the simulation clock "
            f"({snapshot.observed_at.isoformat()} > {clock.instant().isoformat()})"
        )

    submitted = clock.instant() if submitted_at is None else as_aware_utc(submitted_at)
    if not clock.permits(submitted):
        raise ReplayLookaheadError(
            "order submitted_at is after the simulation clock "
            f"({submitted.isoformat()} > {clock.instant().isoformat()})"
        )

    profile = get_execution_profile(replay.profile_name, replay.model_version)
    intent = OrderIntent(
        ticker=ticker,
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
            replay=replay,
            ticker=ticker,
            side=side,
            quantity=quantity,
            decision=decision,
            market_interval=snapshot.interval,
            order_type=order_type.value,
            evaluated_at_naive=as_naive_utc(clock.instant()),
        )
        _touch(replay)
        session.add(replay)
        session.commit()
        session.refresh(replay)
        if fill.id is None:
            session.refresh(fill)
    else:
        session.commit()

    return ReplaySubmitResult(replay=replay, decision=decision, fill=fill)


__all__ = [
    "DEFAULT_REPLAY_CASH",
    "ReplaySubmitResult",
    "advance_replay_clock",
    "close_replay_session",
    "create_replay_session",
    "get_replay_position",
    "get_replay_session",
    "list_replay_fills",
    "list_replay_positions",
    "list_replay_sessions",
    "market_snapshot_for_session",
    "submit_replay_order",
]
