"""`/v1/replay` — isolated ReplaySession over stored 1d PriceBars.

Authenticated. Market truth is server-selected historical bars inside the
session's frozen range. Live ``Trade`` / ``Portfolio`` / Kafka paths are
untouched. Sessions are not deleted.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlmodel import Session

from stockviz.auth import UserIdDep
from stockviz.db import get_session
from stockviz.models import ReplayDrawing, ReplayOrder
from stockviz.routers.indicators import _parse_names
from stockviz.schemas import (
    DrawingOut,
    DrawingPatch,
    DrawingsOut,
    IndicatorsOut,
    ReplayAvailabilityOut,
    ReplayBarOut,
    ReplayDecisionOut,
    ReplayDrawingIn,
    ReplayEpisodeFillOut,
    ReplayEpisodeForensicsOut,
    ReplayEventsOut,
    ReplayFillOut,
    ReplayForensicsOut,
    ReplayJournalIn,
    ReplayJournalOut,
    ReplayMarketOut,
    ReplayOrderIn,
    ReplayOrderOut,
    ReplayPositionOut,
    ReplaySessionCreateIn,
    ReplaySessionListOut,
    ReplaySessionOut,
    ReplaySubmitOut,
    ReplaySummaryOut,
)
from stockviz.services.drills.decks import drill_session_ids, is_hidden_session
from stockviz.services.fee_view import resolve_fee_schedule
from stockviz.services.instruments import is_index_ticker
from stockviz.services.replay import (
    ReplayClosed,
    ReplayCompleted,
    ReplayInsufficientCash,
    ReplayInsufficientPosition,
    ReplayJournalLocked,
    ReplayLagError,
    ReplayLookaheadError,
    ReplayNoMarketError,
    ReplayNotFound,
    ReplayNotTradable,
    ReplayOrderError,
    ReplayOrderNotFound,
    ReplayRangeError,
    ReplaySubmitResult,
    ReplaySymbolNotFound,
    ReplayUnsupportedCurrency,
    advance_replay_session,
    cancel_replay_order,
    cancel_replay_session,
    create_replay_session,
    default_starting_cash,
    get_next_session_bar,
    get_replay_session,
    get_session_bar,
    get_visible_replay_history,
    list_replay_fills,
    list_replay_orders,
    list_replay_positions,
    list_replay_sessions,
    lock_replay_session,
    open_replay_orders,
    submit_replay_order,
)
from stockviz.services.replay import drawings as replay_drawings
from stockviz.services.replay.context import REPLAY_NEWS_RULE, replay_events, replay_indicators
from stockviz.services.replay.forensics import compute_replay_forensics
from stockviz.services.replay.journal import get_replay_journal, update_replay_journal
from stockviz.services.replay.lag import lag_days_for, lag_waived_for, latest_allowed_end
from stockviz.services.replay.market import get_replay_availability
from stockviz.services.replay.session import session_can_advance
from stockviz.services.replay.summary import compute_replay_summary
from stockviz.services.replay.timeutil import as_aware_utc
from stockviz.services.simulation import (
    OrderSide,
    SimulationClockError,
    SimulationOrderType,
)
from stockviz.services.simulation.contracts import FillDecision

router = APIRouter(prefix="/v1/replay", tags=["replay"])

SessionDep = Annotated[Session, Depends(get_session)]


def _bar_out(bar) -> ReplayBarOut:
    return ReplayBarOut(
        ticker=bar.ticker,
        ts=as_aware_utc(bar.ts),
        interval=bar.interval,
        open=bar.open,
        high=bar.high,
        low=bar.low,
        close=bar.close,
        volume=bar.volume,
    )


def _list_out(replay) -> ReplaySessionListOut:
    return ReplaySessionListOut(
        id=replay.id,
        ticker=replay.ticker,
        start_at=as_aware_utc(replay.start_at),
        current_at=as_aware_utc(replay.current_at),
        end_at=as_aware_utc(replay.end_at),
        status=replay.status,
        starting_cash=replay.starting_cash,
        cash_balance=replay.cash_balance,
        has_next=session_can_advance(replay),
        created_at=as_aware_utc(replay.created_at),
        currency=replay.currency,
    )


def _session_out(db: Session, replay) -> ReplaySessionOut:
    positions = [
        ReplayPositionOut(ticker=row.ticker, quantity=row.quantity, avg_cost=row.avg_cost)
        for row in list_replay_positions(db, replay=replay)
    ]
    has_next = get_next_session_bar(db, replay) is not None
    return ReplaySessionOut(
        id=replay.id,
        ticker=replay.ticker,
        profile_name=replay.profile_name,
        model_version=replay.model_version,
        start_at=as_aware_utc(replay.start_at),
        current_at=as_aware_utc(replay.current_at),
        end_at=as_aware_utc(replay.end_at),
        starting_cash=replay.starting_cash,
        cash_balance=replay.cash_balance,
        status=replay.status,
        has_next=has_next,
        completed_at=as_aware_utc(replay.completed_at) if replay.completed_at else None,
        created_at=as_aware_utc(replay.created_at),
        updated_at=as_aware_utc(replay.updated_at),
        positions=positions,
        currency=replay.currency,
        fee_schedule=replay.fee_schedule,
        lag_override=replay.lag_override,
        tradable=not is_index_ticker(replay.ticker),
        open_orders=len(open_replay_orders(db, replay=replay)),
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
        fees=row.fees,
        fee_lines=list(row.fee_lines or []),  # pyright: ignore[reportArgumentType]
        order_id=row.order_id,
    )


def _order_out(row: ReplayOrder) -> ReplayOrderOut:
    assert row.id is not None
    return ReplayOrderOut(
        id=row.id,
        session_id=row.session_id,
        ticker=row.ticker,
        side=row.side,  # pyright: ignore[reportArgumentType]
        order_type=row.order_type,  # pyright: ignore[reportArgumentType]
        quantity=row.quantity,
        limit_price=row.limit_price,
        status=row.status,  # pyright: ignore[reportArgumentType]
        placed_at=as_aware_utc(row.placed_at),
        resolved_at=as_aware_utc(row.resolved_at) if row.resolved_at else None,
        reason=row.reason,
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
        decision=_decision_out(result.decision) if result.decision is not None else None,
        fill=_fill_out(result.fill) if result.fill is not None else None,
        order=_order_out(result.order) if result.order is not None else None,
    )


def _summary_out(db: Session, replay) -> ReplaySummaryOut:
    summary = compute_replay_summary(db, replay)
    return ReplaySummaryOut(
        ticker=replay.ticker,
        status=replay.status,
        current_at=as_aware_utc(replay.current_at),
        current_close=summary.current_close,
        cash=summary.cash,
        starting_cash=summary.starting_cash,
        positions_market_value=summary.positions_market_value,
        equity=summary.equity,
        realized_pnl=summary.realized_pnl,
        unrealized_pnl=summary.unrealized_pnl,
        total_pnl=summary.total_pnl,
        return_pct=summary.return_pct,
        fills_count=summary.fills_count,
        has_next=summary.has_next,
        visible_high=summary.visible_high,
        visible_low=summary.visible_low,
        currency=replay.currency,
        fees_paid=summary.fees_paid,
    )


def _load(db: Session, session_id: int, user_id: int):
    try:
        replay = get_replay_session(db, session_id=session_id, user_id=user_id)
    except ReplayNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    # A4.7: an anonymised drill's session is reached through /v1/drills only,
    # until it is revealed (these routes name the ticker and the real dates).
    if is_hidden_session(db, session_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Replay session {session_id} not found")
    return replay


@router.get("/availability", response_model=ReplayAvailabilityOut)
def get_replay_ticker_availability(
    session: SessionDep,
    user_id: UserIdDep,
    ticker: Annotated[str, Query(min_length=1, max_length=16)],
) -> ReplayAvailabilityOut:
    """Stored 1d bar range for the Replay Lab date picker."""

    try:
        symbol, first, last, count = get_replay_availability(session, ticker=ticker)
    except ReplaySymbolNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except (ReplayRangeError, ReplayUnsupportedCurrency) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    currency = (symbol.currency or "USD").upper()
    waived = lag_days_for(symbol.ticker) > 0 and lag_waived_for(user_id)
    return ReplayAvailabilityOut(
        ticker=symbol.ticker,
        currency=currency,
        first_bar=as_aware_utc(first.ts),
        last_bar=as_aware_utc(last.ts),
        bars_count=count,
        lag_days=lag_days_for(symbol.ticker),
        max_end=None if waived else latest_allowed_end(symbol.ticker),
        lag_waived=waived,
        default_starting_cash=default_starting_cash(currency),
        fee_schedule=resolve_fee_schedule("auto", symbol.ticker),
        tradable=not is_index_ticker(symbol.ticker),
    )


@router.post("/sessions", response_model=ReplaySessionOut, status_code=status.HTTP_201_CREATED)
def post_replay_session(
    body: ReplaySessionCreateIn, session: SessionDep, user_id: UserIdDep
) -> ReplaySessionOut:
    """Create an isolated replay book over a frozen stored-1d ticker range."""

    try:
        replay = create_replay_session(
            session,
            user_id=user_id,
            ticker=body.ticker,
            start_at=body.start_at,
            end_at=body.end_at,
            starting_cash=body.starting_cash,
        )
    except ReplaySymbolNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except (ReplayRangeError, ReplayLagError, ValueError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return _session_out(session, replay)


@router.get("/sessions", response_model=list[ReplaySessionListOut])
def get_replay_sessions(session: SessionDep, user_id: UserIdDep) -> list[ReplaySessionListOut]:
    drills = drill_session_ids(session, user_id)
    return [
        _list_out(row)
        for row in list_replay_sessions(session, user_id=user_id)
        if row.id not in drills
    ]


@router.get("/sessions/{session_id}", response_model=ReplaySessionOut)
def get_one_replay_session(
    session_id: int, session: SessionDep, user_id: UserIdDep
) -> ReplaySessionOut:
    replay = _load(session, session_id, user_id)
    return _session_out(session, replay)


@router.post("/sessions/{session_id}/advance", response_model=ReplaySessionOut)
def post_replay_advance(
    session_id: int,
    session: SessionDep,
    user_id: UserIdDep,
    expected_current_at: datetime | None = None,
) -> ReplaySessionOut:
    """Advance one stored 1d bar; from the last bar, complete the session.

    Pass ``expected_current_at`` (the bar on screen): a repeated request then
    changes nothing (audit SR-10).
    """

    replay = _load(session, session_id, user_id)
    try:
        replay = advance_replay_session(
            session, replay=replay, expected_current_at=expected_current_at
        )
    except (ReplayClosed, ReplayCompleted) as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except SimulationClockError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return _session_out(session, replay)


@router.post("/sessions/{session_id}/cancel", response_model=ReplaySessionOut)
def post_replay_cancel(
    session_id: int, session: SessionDep, user_id: UserIdDep
) -> ReplaySessionOut:
    replay = _load(session, session_id, user_id)
    try:
        replay = cancel_replay_session(session, replay=replay)
    except ReplayCompleted as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return _session_out(session, replay)


@router.get("/sessions/{session_id}/market", response_model=ReplayMarketOut)
def get_replay_market(session_id: int, session: SessionDep, user_id: UserIdDep) -> ReplayMarketOut:
    replay = _load(session, session_id, user_id)
    try:
        bar = get_session_bar(session, replay)
    except ReplayNoMarketError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return ReplayMarketOut(
        ticker=replay.ticker,
        current_at=as_aware_utc(replay.current_at),
        start_at=as_aware_utc(replay.start_at),
        end_at=as_aware_utc(replay.end_at),
        has_next=get_next_session_bar(session, replay) is not None,
        status=replay.status,
        bar=_bar_out(bar),
    )


@router.get("/sessions/{session_id}/history", response_model=list[ReplayBarOut])
def get_replay_history(
    session_id: int, session: SessionDep, user_id: UserIdDep
) -> list[ReplayBarOut]:
    replay = _load(session, session_id, user_id)
    return [_bar_out(bar) for bar in get_visible_replay_history(session, replay)]


@router.get("/sessions/{session_id}/summary", response_model=ReplaySummaryOut)
def get_replay_summary(
    session_id: int, session: SessionDep, user_id: UserIdDep
) -> ReplaySummaryOut:
    replay = _load(session, session_id, user_id)
    try:
        return _summary_out(session, replay)
    except ReplayNoMarketError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc


@router.post("/sessions/{session_id}/orders", response_model=ReplaySubmitOut)
def post_replay_order(
    session_id: int, body: ReplayOrderIn, session: SessionDep, user_id: UserIdDep
) -> ReplaySubmitOut:
    """Fill against the server-authoritative current bar. Intent only."""

    replay = _load(session, session_id, user_id)
    try:
        result = submit_replay_order(
            session,
            replay=replay,
            side=OrderSide(body.side),
            order_type=SimulationOrderType(body.order_type),
            quantity=body.quantity,
            limit_price=body.limit_price,
        )
    except (ReplayClosed, ReplayCompleted) as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except ReplayLookaheadError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except ReplayNoMarketError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except (ReplayInsufficientCash, ReplayInsufficientPosition) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    except (ReplayNotTradable, ReplayOrderError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except (SimulationClockError, TypeError, ValueError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return _submit_out(session, result)


@router.get("/sessions/{session_id}/orders", response_model=list[ReplayOrderOut])
def get_replay_orders(
    session_id: int, session: SessionDep, user_id: UserIdDep
) -> list[ReplayOrderOut]:
    """A4.6: every resting order of the session, oldest first."""

    replay = _load(session, session_id, user_id)
    return [_order_out(row) for row in list_replay_orders(session, replay=replay)]


@router.post("/sessions/{session_id}/orders/{order_id}/cancel", response_model=ReplayOrderOut)
def post_replay_order_cancel(
    session_id: int, order_id: int, session: SessionDep, user_id: UserIdDep
) -> ReplayOrderOut:
    """A4.6: cancel one open resting order (409 when it is not open)."""

    _load(session, session_id, user_id)
    try:
        locked = lock_replay_session(session, session_id=session_id, user_id=user_id)
        if locked.status != "active":
            raise ReplayClosed(f"Replay session {session_id} is not active")
        row = cancel_replay_order(session, replay=locked, order_id=order_id)
    except ReplayOrderNotFound as exc:
        session.rollback()
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except (ReplayClosed, ReplayOrderError) as exc:
        session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return _order_out(row)


@router.get("/sessions/{session_id}/indicators", response_model=IndicatorsOut)
def get_replay_indicators(
    session_id: int,
    session: SessionDep,
    user_id: UserIdDep,
    names: Annotated[str, Query(description="e.g. sma_20,rsi_14,macd,bb_20_2")],
) -> IndicatorsOut:
    """A4.6: indicators over the visible bars only (daily), warmed up on the
    stored bars before ``start_at``. Never reads a bar after ``current_at``."""

    replay = _load(session, session_id, user_id)
    return replay_indicators(session, replay, _parse_names(names))


@router.get("/sessions/{session_id}/events", response_model=ReplayEventsOut)
def get_replay_events(session_id: int, session: SessionDep, user_id: UserIdDep) -> ReplayEventsOut:
    """A4.6: news whose ``available_at`` is at or before the clock, and the
    session's fills. The replay chart never calls the live events route."""

    replay = _load(session, session_id, user_id)
    assert replay.id is not None
    return ReplayEventsOut(
        session_id=replay.id,
        ticker=replay.ticker,
        current_at=as_aware_utc(replay.current_at),
        news_rule=REPLAY_NEWS_RULE,
        events=replay_events(session, replay),
    )


@router.get("/sessions/{session_id}/drawings", response_model=DrawingsOut)
def get_replay_drawings(session_id: int, session: SessionDep, user_id: UserIdDep) -> DrawingsOut:
    """A4.6: the drawings made in this session only (``first_bar``/``last_bar``
    bound anchors: the session's first bar to its clock)."""

    return drawings_of(session, _load(session, session_id, user_id))


def drawings_of(session: Session, replay) -> DrawingsOut:
    first, last = replay_drawings.anchor_range(replay)
    return DrawingsOut(
        ticker=replay.ticker,
        drawings=[
            replay_drawings.drawing_out(row, replay.ticker)
            for row in replay_drawings.list_drawings(session, replay)
        ],
        limit=replay_drawings.MAX_REPLAY_DRAWINGS,
        first_bar=first,
        last_bar=last,
    )


@router.post(
    "/sessions/{session_id}/drawings",
    response_model=DrawingOut,
    status_code=status.HTTP_201_CREATED,
)
def post_replay_drawing(
    session_id: int, body: ReplayDrawingIn, session: SessionDep, user_id: UserIdDep
) -> DrawingOut:
    return create_drawing(session, _load(session, session_id, user_id), body)


def create_drawing(session: Session, replay, body: ReplayDrawingIn) -> DrawingOut:
    label = body.label.strip() if body.label and body.label.strip() else None
    replay_drawings.validate(replay, body.kind, body.points, label)
    if replay_drawings.count(session, replay) >= replay_drawings.MAX_REPLAY_DRAWINGS:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"At most {replay_drawings.MAX_REPLAY_DRAWINGS} drawings in one session",
        )
    assert replay.id is not None
    row = ReplayDrawing(
        session_id=replay.id,
        kind=body.kind,
        points=replay_drawings.points_json(body.points),
        style=body.style.model_dump(),
        label=label,
        locked=body.locked,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return replay_drawings.drawing_out(row, replay.ticker)


@router.patch("/sessions/{session_id}/drawings/{drawing_id}", response_model=DrawingOut)
def patch_replay_drawing(
    session_id: int,
    drawing_id: int,
    body: DrawingPatch,
    session: SessionDep,
    user_id: UserIdDep,
) -> DrawingOut:
    return patch_drawing(session, _load(session, session_id, user_id), drawing_id, body)


def patch_drawing(session: Session, replay, drawing_id: int, body: DrawingPatch) -> DrawingOut:
    row = replay_drawings.owned(session, replay, drawing_id)
    sent = body.model_fields_set
    edits = sent - {"locked"}
    if row.locked and edits and body.locked is not False:
        raise HTTPException(status.HTTP_409_CONFLICT, "The drawing is locked; unlock it first")
    if "locked" in sent:
        if body.locked is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "locked cannot be null")
        row.locked = body.locked
    label = row.label
    if "label" in sent:
        label = body.label.strip() if body.label and body.label.strip() else None
    if "style" in sent:
        if body.style is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "style cannot be null")
        row.style = body.style.model_dump()
    points = replay_drawings.points_of(row)
    if "points" in sent:
        if body.points is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "points cannot be null")
        points = body.points
    if {"points", "label"} & sent:
        replay_drawings.validate(replay, row.kind, points, label)
        row.points = replay_drawings.points_json(points)
        row.label = label
    replay_drawings.touch(row)
    session.add(row)
    session.commit()
    session.refresh(row)
    return replay_drawings.drawing_out(row, replay.ticker)


@router.delete(
    "/sessions/{session_id}/drawings/{drawing_id}", status_code=status.HTTP_204_NO_CONTENT
)
def delete_replay_drawing(
    session_id: int, drawing_id: int, session: SessionDep, user_id: UserIdDep
) -> Response:
    delete_drawing(session, _load(session, session_id, user_id), drawing_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def delete_drawing(session: Session, replay, drawing_id: int) -> None:
    row = replay_drawings.owned(session, replay, drawing_id)
    if row.locked:
        raise HTTPException(status.HTTP_409_CONFLICT, "The drawing is locked; unlock it first")
    session.delete(row)
    session.commit()


@router.get("/sessions/{session_id}/fills", response_model=list[ReplayFillOut])
def get_replay_fills(
    session_id: int, session: SessionDep, user_id: UserIdDep
) -> list[ReplayFillOut]:
    replay = _load(session, session_id, user_id)
    return [_fill_out(row) for row in list_replay_fills(session, replay=replay)]


def _episode_fill_out(fill) -> ReplayEpisodeFillOut:
    return ReplayEpisodeFillOut(
        id=fill.id,
        ticker=fill.ticker,
        side=fill.side,
        quantity=fill.quantity,
        fill_price=fill.fill_price,
        realized_pnl=fill.realized_pnl,
        profile_name=fill.profile_name,
        model_version=fill.model_version,
        reference_price=fill.reference_price,
        reason=fill.reason,
        assumptions=list(fill.assumptions),
        market_interval=fill.market_interval,
        order_type=fill.order_type,
        evaluated_at=as_aware_utc(fill.evaluated_at),
        created_at=as_aware_utc(fill.created_at),
        equity_after=fill.equity_after,
        concentration_pct=fill.concentration_pct,
        fees=fill.fees,
    )


def _episode_out(episode) -> ReplayEpisodeForensicsOut:
    return ReplayEpisodeForensicsOut(
        index=episode.index,
        ticker=episode.ticker,
        opened_at=as_aware_utc(episode.opened_at),
        closed_at=as_aware_utc(episode.closed_at) if episode.closed_at else None,
        status=episode.status,
        entry_price=episode.entry_price,
        exit_price=episode.exit_price,
        entry_quantity=episode.entry_quantity,
        peak_quantity=episode.peak_quantity,
        weighted_entry_price=episode.weighted_entry_price,
        weighted_exit_price=episode.weighted_exit_price,
        realized_pnl=episode.realized_pnl,
        unrealized_pnl=episode.unrealized_pnl,
        return_pct=episode.return_pct,
        holding_bars=episode.holding_bars,
        holding_calendar_days=episode.holding_calendar_days,
        mae_amount=episode.mae_amount,
        mae_pct=episode.mae_pct,
        mfe_amount=episode.mfe_amount,
        mfe_pct=episode.mfe_pct,
        benchmark_return_pct=episode.benchmark_return_pct,
        excess_return_pct=episode.excess_return_pct,
        max_position_pct=episode.max_position_pct,
        entry_equity=episode.entry_equity,
        peak_exposure=episode.peak_exposure,
        fills=[_episode_fill_out(fill) for fill in episode.fills],
        fees=episode.fees,
    )


def _forensics_out(db: Session, replay) -> ReplayForensicsOut:
    result = compute_replay_forensics(db, replay)
    return ReplayForensicsOut(
        ticker=result.ticker,
        status=result.status,
        analysis_scope=result.analysis_scope,
        analysis_at=as_aware_utc(result.analysis_at),
        starting_cash=result.starting_cash,
        equity=result.equity,
        replay_return_pct=result.replay_return_pct,
        buy_hold_return_pct=result.buy_hold_return_pct,
        excess_return_pct=result.excess_return_pct,
        max_drawdown_pct=result.max_drawdown_pct,
        max_concentration_pct=result.max_concentration_pct,
        fills_count=result.fills_count,
        episodes_count=result.episodes_count,
        closed_episodes_count=result.closed_episodes_count,
        open_episodes_count=result.open_episodes_count,
        episodes=[_episode_out(item) for item in result.episodes],
        currency=replay.currency,
    )


def _journal_out(row) -> ReplayJournalOut:
    """A5.4: the session's trade plan, in the journal's shape."""
    locked_at = row.locked_at or row.first_fill_at
    return ReplayJournalOut(
        session_id=row.replay_session_id,
        thesis=row.thesis_text,
        invalidation=row.invalidation,
        expected_holding_bars=row.horizon_bars,
        confidence=row.confidence,
        reflection=row.notes,
        locked=row.frozen,
        locked_at=as_aware_utc(locked_at) if locked_at else None,
        written_after_entry=row.written_after_entry,
        created_at=as_aware_utc(row.created_at),
        updated_at=as_aware_utc(row.updated_at),
    )


@router.get("/sessions/{session_id}/forensics", response_model=ReplayForensicsOut)
def get_replay_session_forensics(
    session_id: int, session: SessionDep, user_id: UserIdDep
) -> ReplayForensicsOut:
    """Deterministic post-trade analytics through the replay clock only."""

    replay = _load(session, session_id, user_id)
    try:
        return _forensics_out(session, replay)
    except ReplayNoMarketError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc


@router.get("/sessions/{session_id}/journal", response_model=ReplayJournalOut)
def get_replay_session_journal(
    session_id: int, session: SessionDep, user_id: UserIdDep
) -> ReplayJournalOut:
    replay = _load(session, session_id, user_id)
    return _journal_out(get_replay_journal(session, replay=replay))


@router.put("/sessions/{session_id}/journal", response_model=ReplayJournalOut)
def put_replay_session_journal(
    session_id: int, body: ReplayJournalIn, session: SessionDep, user_id: UserIdDep
) -> ReplayJournalOut:
    replay = _load(session, session_id, user_id)
    try:
        row = update_replay_journal(
            session,
            replay=replay,
            thesis=body.thesis,
            invalidation=body.invalidation,
            expected_holding_bars=body.expected_holding_bars,
            confidence=body.confidence,
            reflection=body.reflection,
        )
    except ReplayJournalLocked as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return _journal_out(row)
