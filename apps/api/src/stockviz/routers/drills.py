"""`/v1/drills` — drills and decks (A4.7, M9.3). Authenticated.

A deck is K replays seeded from a rule's real false-to-true triggers. Every
drill route answers in the drill's anonymised view until it is revealed
(``services/drills/anonymise.py``): the symbol is "Stock A", dates are
shifted by whole weeks, headlines are hidden. The replay session behind a
drill is only reachable here while it is anonymised (``/v1/replay`` 404s).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel
from sqlmodel import Session

from stockviz.auth import UserIdDep
from stockviz.db import get_session
from stockviz.models import Symbol
from stockviz.routers import replay as replay_routes
from stockviz.routers.indicators import _parse_names
from stockviz.schemas import (
    DrawingOut,
    DrawingPatch,
    DrawingPoint,
    DrawingsOut,
    DrillDeckIn,
    DrillDeckOut,
    DrillOut,
    DrillPlanIn,
    DrillPlanOut,
    DrillRevealOut,
    IndicatorsOut,
    ReplayDrawingIn,
    ReplayEventsOut,
    ReplayOrderIn,
    ReplayOrderOut,
    ReplaySessionOut,
    ReplaySubmitOut,
)
from stockviz.services.backtest.strategy_run import StrategyNeedsUser, StrategyNotFound
from stockviz.services.bars.resample import bar_date
from stockviz.services.drills import decks
from stockviz.services.drills.anonymise import NEWS_NOTE_ANONYMISED, NEWS_NOTE_REVEALED, Mask
from stockviz.services.dsl import RuleError
from stockviz.services.markets.calendar import venue_for_ticker
from stockviz.services.replay import (
    ReplayClosed,
    ReplayCompleted,
    ReplayInsufficientCash,
    ReplayInsufficientPosition,
    ReplayLagError,
    ReplayLookaheadError,
    ReplayNoMarketError,
    ReplayNotTradable,
    ReplayOrderError,
    ReplayOrderNotFound,
    ReplayRangeError,
    advance_replay_session,
    cancel_replay_order,
    get_session_bar,
    get_visible_replay_history,
    list_replay_fills,
    list_replay_orders,
    lock_replay_session,
    submit_replay_order,
)
from stockviz.services.replay.context import REPLAY_NEWS_RULE, replay_events, replay_indicators
from stockviz.services.replay.timeutil import as_aware_utc
from stockviz.services.scan_event_study import ScanStudyError
from stockviz.services.setups.rules import error_out
from stockviz.services.simulation import OrderSide, SimulationClockError, SimulationOrderType

router = APIRouter(prefix="/v1/drills", tags=["drills"])

SessionDep = Annotated[Session, Depends(get_session)]

DATE_NOTE = (
    "Dates are shifted by a whole number of weeks, so each weekday is the real one; prices "
    "and returns are unchanged. The real dates are shown when the drill is revealed."
)


def _ctx(db: Session, drill_id: int, user_id: int) -> decks.DrillContext:
    try:
        return decks.load_drill(db, drill_id, user_id)
    except decks.DrillNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


def _mask[M: BaseModel](mask: Mask | None, model: M) -> M:
    return mask.apply(model) if mask is not None else model


def _http(code: int, exc: Exception, mask: Mask | None) -> HTTPException:
    detail = str(exc)
    return HTTPException(code, mask.text(detail) if mask is not None else detail)


def _guard(mask: Mask | None, work: Callable[[], Any]) -> Any:
    """Run ``work``; map the replay errors as the replay routes do, with the
    message masked (an error can name the ticker or a date)."""
    try:
        return work()
    except HTTPException as exc:
        if mask is not None and isinstance(exc.detail, str):
            raise HTTPException(exc.status_code, mask.text(exc.detail)) from exc
        raise
    except (ReplayClosed, ReplayCompleted, ReplayNoMarketError, decks.DrillConflict) as exc:
        raise _http(status.HTTP_409_CONFLICT, exc, mask) from exc
    except (ReplayInsufficientCash, ReplayInsufficientPosition) as exc:
        raise _http(status.HTTP_422_UNPROCESSABLE_CONTENT, exc, mask) from exc
    except ReplayOrderNotFound as exc:
        raise _http(status.HTTP_404_NOT_FOUND, exc, mask) from exc
    except (
        ReplayLookaheadError,
        ReplayNotTradable,
        ReplayOrderError,
        SimulationClockError,
        TypeError,
        ValueError,
    ) as exc:
        raise _http(status.HTTP_400_BAD_REQUEST, exc, mask) from exc


# --- decks ---------------------------------------------------------------------


@router.post("/decks", response_model=DrillDeckOut, status_code=status.HTTP_201_CREATED)
def post_deck(body: DrillDeckIn, session: SessionDep, user_id: UserIdDep) -> DrillDeckOut:
    """Find the rule's false-to-true triggers across the universe, sample K
    with the seed, and open one replay session per drill."""
    try:
        deck = decks.create_deck(session, body, user_id=user_id)
    except StrategyNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except StrategyNeedsUser as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc
    except RuleError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, error_out(exc).model_dump()
        ) from exc
    except decks.DrillConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except (ScanStudyError, decks.DrillError, ReplayRangeError, ReplayLagError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return decks.deck_out(session, deck)


@router.get("/decks", response_model=list[DrillDeckOut])
def get_decks(session: SessionDep, user_id: UserIdDep) -> list[DrillDeckOut]:
    return [decks.deck_out(session, d) for d in decks.list_decks(session, user_id)]


def _deck(session: Session, deck_id: int, user_id: int):
    try:
        return decks.owned_deck(session, deck_id, user_id)
    except decks.DrillNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


@router.get("/decks/{deck_id}", response_model=DrillDeckOut)
def get_deck(deck_id: int, session: SessionDep, user_id: UserIdDep) -> DrillDeckOut:
    return decks.deck_out(session, _deck(session, deck_id, user_id))


@router.delete("/decks/{deck_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_deck(deck_id: int, session: SessionDep, user_id: UserIdDep) -> Response:
    """Deletes the deck, its drills, their plans and their replay sessions."""
    decks.delete_deck(session, _deck(session, deck_id, user_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- one drill -------------------------------------------------------------------


def _reveal_out(session: Session, ctx: decks.DrillContext) -> DrillRevealOut | None:
    if ctx.drill.revealed_at is None:
        return None
    symbol = session.get(Symbol, ctx.drill.ticker)
    venue = venue_for_ticker(ctx.drill.ticker)
    after, nxt = decks.after_trigger(session, ctx)
    offset = ctx.drill.date_offset_weeks if ctx.deck.anonymised else 0
    shown = Mask(ctx.drill.ticker, "", offset).shift_date(ctx.drill.trigger_date)
    return DrillRevealOut(
        ticker=ctx.drill.ticker,
        name=symbol.name if symbol else None,
        sector=symbol.sector if symbol else None,
        currency=ctx.replay.currency,
        trigger_date=ctx.drill.trigger_date,
        session_start=bar_date(ctx.replay.start_at, venue),
        session_end=bar_date(ctx.replay.end_at, venue),
        shown_trigger_date=shown,
        date_offset_weeks=offset,
        after=after,
        next_bars=[replay_routes._bar_out(b) for b in nxt],
    )


def _drill_out(session: Session, ctx: decks.DrillContext) -> DrillOut:
    mask = decks.mask_for(session, ctx)
    replay = ctx.replay
    plan = decks.plan_of(session, replay)
    assert ctx.drill.id is not None
    out = DrillOut(
        id=ctx.drill.id,
        deck_id=ctx.deck.id or 0,
        deck_name=ctx.deck.name,
        position=ctx.drill.position,
        label=mask.label if mask is not None else ctx.drill.ticker,
        status=decks.status_of(session, ctx, plan),  # pyright: ignore[reportArgumentType]
        anonymised=mask is not None,
        date_note=DATE_NOTE if mask is not None else None,
        news_note=NEWS_NOTE_ANONYMISED if mask is not None else NEWS_NOTE_REVEALED,
        trigger_at=as_aware_utc(ctx.drill.trigger_at),
        session=replay_routes._session_out(session, replay),
        summary=replay_routes._summary_out(session, replay),
        bar=replay_routes._bar_out(get_session_bar(session, replay)),
        history=[replay_routes._bar_out(b) for b in get_visible_replay_history(session, replay)],
        orders=[replay_routes._order_out(o) for o in list_replay_orders(session, replay=replay)],
        fills=[replay_routes._fill_out(f) for f in list_replay_fills(session, replay=replay)],
        plan=decks.plan_out(session, ctx, plan) if plan is not None else None,
        needs_plan=plan is None,
        score=decks.score_of(session, ctx, plan),
        reveal=_reveal_out(session, ctx),
    )
    if mask is None:
        return out
    # The deck's name holds the rule and universe, never the ticker; mask anyway.
    return mask.apply(out)


@router.get("/{drill_id}", response_model=DrillOut)
def get_drill(drill_id: int, session: SessionDep, user_id: UserIdDep) -> DrillOut:
    ctx = _ctx(session, drill_id, user_id)
    return _guard(decks.mask_for(session, ctx), lambda: _drill_out(session, ctx))


@router.put("/{drill_id}/plan", response_model=DrillPlanOut)
def put_plan(
    drill_id: int, body: DrillPlanIn, session: SessionDep, user_id: UserIdDep
) -> DrillPlanOut:
    """The plan before the first order: planned entry, stop and size (long).
    Editable until the first fill; 409 after."""
    ctx = _ctx(session, drill_id, user_id)
    mask = decks.mask_for(session, ctx)
    plan = _guard(mask, lambda: decks.put_plan(session, ctx, body))
    return _mask(mask, decks.plan_out(session, ctx, plan))


@router.post("/{drill_id}/orders", response_model=ReplaySubmitOut)
def post_order(
    drill_id: int, body: ReplayOrderIn, session: SessionDep, user_id: UserIdDep
) -> ReplaySubmitOut:
    """As the replay route, after a plan exists (409 without one)."""
    ctx = _ctx(session, drill_id, user_id)
    mask = decks.mask_for(session, ctx)

    def work() -> ReplaySubmitOut:
        decks.require_plan(session, ctx)
        result = submit_replay_order(
            session,
            replay=ctx.replay,
            side=OrderSide(body.side),
            order_type=SimulationOrderType(body.order_type),
            quantity=body.quantity,
            limit_price=body.limit_price,
        )
        return replay_routes._submit_out(session, result)

    return _mask(mask, _guard(mask, work))


@router.post("/{drill_id}/orders/{order_id}/cancel", response_model=ReplayOrderOut)
def post_order_cancel(
    drill_id: int, order_id: int, session: SessionDep, user_id: UserIdDep
) -> ReplayOrderOut:
    ctx = _ctx(session, drill_id, user_id)
    mask = decks.mask_for(session, ctx)

    def work() -> ReplayOrderOut:
        assert ctx.replay.id is not None
        try:
            locked = lock_replay_session(session, session_id=ctx.replay.id, user_id=user_id)
            if locked.status != "active":
                raise ReplayClosed("The drill's session is not active")
            return replay_routes._order_out(
                cancel_replay_order(session, replay=locked, order_id=order_id)
            )
        except Exception:
            session.rollback()
            raise

    return _mask(mask, _guard(mask, work))


@router.post("/{drill_id}/advance", response_model=ReplaySessionOut)
def post_advance(
    drill_id: int,
    session: SessionDep,
    user_id: UserIdDep,
    expected_current_at: datetime | None = None,
) -> ReplaySessionOut:
    """Next bar; from the last bar, the session completes (then reveal).
    ``expected_current_at`` is the date on screen (shifted, when anonymised)."""
    ctx = _ctx(session, drill_id, user_id)
    mask = decks.mask_for(session, ctx)
    expected = expected_current_at
    if expected is not None and mask is not None:
        expected = mask.unshift_dt(expected)

    def work() -> ReplaySessionOut:
        replay = advance_replay_session(session, replay=ctx.replay, expected_current_at=expected)
        return replay_routes._session_out(session, replay)

    return _mask(mask, _guard(mask, work))


@router.get("/{drill_id}/indicators", response_model=IndicatorsOut)
def get_indicators(
    drill_id: int,
    session: SessionDep,
    user_id: UserIdDep,
    names: Annotated[str, Query(description="e.g. sma_20,rsi_14,macd,bb_20_2")],
) -> IndicatorsOut:
    """The replay's indicators (bars up to the clock), masked."""
    ctx = _ctx(session, drill_id, user_id)
    mask = decks.mask_for(session, ctx)
    out = _guard(mask, lambda: replay_indicators(session, ctx.replay, _parse_names(names)))
    return _mask(mask, out)


@router.get("/{drill_id}/events", response_model=ReplayEventsOut)
def get_events(drill_id: int, session: SessionDep, user_id: UserIdDep) -> ReplayEventsOut:
    """News known by the clock and the drill's fills. Anonymised: news markers
    carry the count only (no headlines, sources or links)."""
    ctx = _ctx(session, drill_id, user_id)
    mask = decks.mask_for(session, ctx)
    replay = ctx.replay
    assert replay.id is not None
    out = ReplayEventsOut(
        session_id=replay.id,
        ticker=replay.ticker,
        current_at=as_aware_utc(replay.current_at),
        news_rule=REPLAY_NEWS_RULE,
        events=replay_events(session, replay),
    )
    return mask.events(out) if mask is not None else out


# --- drawings (the session's own, dates translated) ------------------------------


def _points_in(mask: Mask | None, points: list[DrawingPoint]) -> list[DrawingPoint]:
    if mask is None:
        return points
    return [
        p.model_copy(update={"ts": mask.unshift_date(p.ts) if p.ts is not None else None})
        for p in points
    ]


@router.get("/{drill_id}/drawings", response_model=DrawingsOut)
def get_drawings(drill_id: int, session: SessionDep, user_id: UserIdDep) -> DrawingsOut:
    ctx = _ctx(session, drill_id, user_id)
    mask = decks.mask_for(session, ctx)
    return _mask(mask, replay_routes.drawings_of(session, ctx.replay))


@router.post("/{drill_id}/drawings", response_model=DrawingOut, status_code=201)
def post_drawing(
    drill_id: int, body: ReplayDrawingIn, session: SessionDep, user_id: UserIdDep
) -> DrawingOut:
    ctx = _ctx(session, drill_id, user_id)
    mask = decks.mask_for(session, ctx)
    real = body.model_copy(update={"points": _points_in(mask, body.points)})
    out = _guard(mask, lambda: replay_routes.create_drawing(session, ctx.replay, real))
    return _mask(mask, out)


@router.patch("/{drill_id}/drawings/{drawing_id}", response_model=DrawingOut)
def patch_drawing(
    drill_id: int,
    drawing_id: int,
    body: DrawingPatch,
    session: SessionDep,
    user_id: UserIdDep,
) -> DrawingOut:
    ctx = _ctx(session, drill_id, user_id)
    mask = decks.mask_for(session, ctx)
    real = body
    if body.points is not None:
        real = body.model_copy(update={"points": _points_in(mask, body.points)})
    out = _guard(mask, lambda: replay_routes.patch_drawing(session, ctx.replay, drawing_id, real))
    return _mask(mask, out)


@router.delete("/{drill_id}/drawings/{drawing_id}", status_code=204)
def delete_drawing(
    drill_id: int, drawing_id: int, session: SessionDep, user_id: UserIdDep
) -> Response:
    ctx = _ctx(session, drill_id, user_id)
    mask = decks.mask_for(session, ctx)
    _guard(mask, lambda: replay_routes.delete_drawing(session, ctx.replay, drawing_id))
    return Response(status_code=204)


@router.post("/{drill_id}/reveal", response_model=DrillOut)
def post_reveal(drill_id: int, session: SessionDep, user_id: UserIdDep) -> DrillOut:
    """Ends the session if it is still running and reveals the ticker, the
    company, the real dates, what happened next and the process score."""
    ctx = _ctx(session, drill_id, user_id)
    ctx = decks.reveal(session, ctx)
    return _drill_out(session, ctx)
