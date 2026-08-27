"""`/v1/replay` — isolated ReplaySession + simulation clock (SIM-05).

Authenticated. Caller-supplied snapshots only; this router does not read
``price_bars``. Live ``Trade`` / ``Portfolio`` / Kafka paths are untouched.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session

from stockviz.auth import UserIdDep
from stockviz.db import get_session
from stockviz.schemas import (
    ReplayClockIn,
    ReplayDecisionOut,
    ReplayFillOut,
    ReplayOrderIn,
    ReplayPositionOut,
    ReplaySessionCreateIn,
    ReplaySessionOut,
    ReplaySubmitOut,
)
from stockviz.services.replay import (
    ReplayClosed,
    ReplayInsufficientCash,
    ReplayInsufficientPosition,
    ReplayLookaheadError,
    ReplayNotFound,
    ReplaySubmitResult,
    advance_replay_clock,
    close_replay_session,
    create_replay_session,
    get_replay_session,
    list_replay_fills,
    list_replay_positions,
    list_replay_sessions,
    market_snapshot_for_session,
    submit_replay_order,
)
from stockviz.services.replay.timeutil import as_aware_utc
from stockviz.services.simulation import (
    OrderSide,
    SimulationClockError,
    SimulationOrderType,
    UnknownExecutionProfileError,
)
from stockviz.services.simulation.contracts import FillDecision

router = APIRouter(prefix="/v1/replay", tags=["replay"])

SessionDep = Annotated[Session, Depends(get_session)]


def _session_out(db: Session, replay) -> ReplaySessionOut:
    positions = [
        ReplayPositionOut(ticker=row.ticker, quantity=row.quantity, avg_cost=row.avg_cost)
        for row in list_replay_positions(db, replay=replay)
    ]
    return ReplaySessionOut(
        id=replay.id,
        profile_name=replay.profile_name,
        model_version=replay.model_version,
        clock_now=as_aware_utc(replay.clock_now),
        starting_cash=replay.starting_cash,
        cash_balance=replay.cash_balance,
        status=replay.status,
        created_at=as_aware_utc(replay.created_at),
        updated_at=as_aware_utc(replay.updated_at),
        positions=positions,
    )


def _fill_out(row) -> ReplayFillOut:
    return ReplayFillOut(
        id=row.id,
        session_id=row.session_id,
        ticker=row.ticker,
        side=row.side,
        quantity=row.quantity,
        fill_price=row.fill_price,
        realized_pnl=row.realized_pnl,
        profile_name=row.profile_name,
        model_version=row.model_version,
        reference_price=row.reference_price,
        reason=row.reason,
        assumptions=list(row.assumptions),
        market_interval=row.market_interval,
        order_type=row.order_type,
        evaluated_at=as_aware_utc(row.evaluated_at),
        created_at=as_aware_utc(row.created_at),
    )


def _decision_out(decision: FillDecision) -> ReplayDecisionOut:
    return ReplayDecisionOut(
        status=decision.status.value,
        fill_quantity=decision.fill_quantity,
        fill_price=decision.fill_price,
        remaining_quantity=decision.remaining_quantity,
        reason=decision.trace.reason,
        profile_name=decision.trace.profile,
        model_version=decision.trace.model_version,
        reference_price=decision.trace.reference_price,
        assumptions=list(decision.trace.assumptions),
    )


def _submit_out(db: Session, result: ReplaySubmitResult) -> ReplaySubmitOut:
    return ReplaySubmitOut(
        session=_session_out(db, result.replay),
        decision=_decision_out(result.decision),
        fill=_fill_out(result.fill) if result.fill is not None else None,
    )


def _load(db: Session, session_id: int, user_id: int):
    try:
        return get_replay_session(db, session_id=session_id, user_id=user_id)
    except ReplayNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


@router.post("/sessions", response_model=ReplaySessionOut, status_code=status.HTTP_201_CREATED)
def post_replay_session(
    body: ReplaySessionCreateIn, session: SessionDep, user_id: UserIdDep
) -> ReplaySessionOut:
    """Create an isolated replay book pinned to a registered execution profile."""

    try:
        replay = create_replay_session(
            session,
            user_id=user_id,
            clock_now=body.clock_now,
            starting_cash=body.starting_cash,
            profile_name=body.profile_name,
            model_version=body.model_version,
        )
    except UnknownExecutionProfileError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except (SimulationClockError, ValueError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return _session_out(session, replay)


@router.get("/sessions", response_model=list[ReplaySessionOut])
def get_replay_sessions(session: SessionDep, user_id: UserIdDep) -> list[ReplaySessionOut]:
    return [_session_out(session, row) for row in list_replay_sessions(session, user_id=user_id)]


@router.get("/sessions/{session_id}", response_model=ReplaySessionOut)
def get_one_replay_session(
    session_id: int, session: SessionDep, user_id: UserIdDep
) -> ReplaySessionOut:
    replay = _load(session, session_id, user_id)
    return _session_out(session, replay)


@router.post("/sessions/{session_id}/clock", response_model=ReplaySessionOut)
def post_replay_clock(
    session_id: int, body: ReplayClockIn, session: SessionDep, user_id: UserIdDep
) -> ReplaySessionOut:
    """Advance the simulation clock. Does not walk bars or settle orders."""

    replay = _load(session, session_id, user_id)
    try:
        replay = advance_replay_clock(session, replay=replay, instant=body.now)
    except ReplayClosed as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except (SimulationClockError, ReplayLookaheadError, ValueError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return _session_out(session, replay)


@router.post("/sessions/{session_id}/close", response_model=ReplaySessionOut)
def post_replay_close(session_id: int, session: SessionDep, user_id: UserIdDep) -> ReplaySessionOut:
    replay = _load(session, session_id, user_id)
    replay = close_replay_session(session, replay=replay)
    return _session_out(session, replay)


@router.post("/sessions/{session_id}/orders", response_model=ReplaySubmitOut)
def post_replay_order(
    session_id: int, body: ReplayOrderIn, session: SessionDep, user_id: UserIdDep
) -> ReplaySubmitOut:
    """Evaluate a caller-supplied snapshot at the session clock; fill if the kernel says so."""

    replay = _load(session, session_id, user_id)
    ticker = body.ticker.upper()
    snap_ticker = (body.snapshot.ticker or ticker).upper()
    try:
        snapshot = market_snapshot_for_session(
            replay,
            ticker=snap_ticker,
            interval=body.snapshot.interval,
            open=body.snapshot.open,
            high=body.snapshot.high,
            low=body.snapshot.low,
            close=body.snapshot.close,
            volume=body.snapshot.volume,
            observed_at=body.snapshot.observed_at,
        )
        result = submit_replay_order(
            session,
            replay=replay,
            ticker=ticker,
            side=OrderSide(body.side),
            order_type=SimulationOrderType(body.order_type),
            quantity=body.quantity,
            snapshot=snapshot,
            limit_price=body.limit_price,
            submitted_at=body.submitted_at,
        )
    except ReplayClosed as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except ReplayLookaheadError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except (ReplayInsufficientCash, ReplayInsufficientPosition) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    except (SimulationClockError, TypeError, ValueError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return _submit_out(session, result)


@router.get("/sessions/{session_id}/fills", response_model=list[ReplayFillOut])
def get_replay_fills(
    session_id: int, session: SessionDep, user_id: UserIdDep
) -> list[ReplayFillOut]:
    replay = _load(session, session_id, user_id)
    return [_fill_out(row) for row in list_replay_fills(session, replay=replay)]
