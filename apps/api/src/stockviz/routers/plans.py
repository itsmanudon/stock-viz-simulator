"""`/v1/plans` (A5.4, M10.3): trade plans. Authed, private to the owner.

- ``GET ""``: your plans, newest first. ``?book=<id>`` keeps one book's
  (another user's book 404); ``status``, ``source``, ``setup_version_id`` and
  ``ticker`` filter. Plans of anonymised drills not yet revealed are left
  out (they name the real symbol and dates).
- ``POST ""`` (201): a plan for ``ticker`` in the ``?book=`` paper book (the
  default book when absent; archived and imported books 409). With
  ``link_open_position`` it links the book's open position in the ticker,
  whose fills came first: the plan is "written after entry".
- ``GET``/``PATCH``/``DELETE /{id}``. ``PATCH`` changes the plan fields only
  before the first fill (409 after: the lock), ``notes`` and ``tags`` always,
  and ``status`` (``closed`` an active plan, ``cancelled`` an open one).
  ``DELETE`` (204) only a plan with no fill. Replay and drill plans are read
  only here (409): their journal and plan forms own them.

Orders and trades link a plan with ``trade_plan_id`` or a new ``plan`` on
``POST /v1/trades`` and ``POST /v1/orders`` (``services/plans``).
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Response, status
from sqlmodel import Session, col, select

from stockviz.auth import UserIdDep
from stockviz.db import get_session
from stockviz.models import PendingOrder, Thesis, Trade
from stockviz.models.trade_plan import MAX_PLANS_PER_USER, TradePlan
from stockviz.routers.book_query import BookQuery
from stockviz.schemas import TradePlanIn, TradePlanOut, TradePlanPatch, TradePlansOut
from stockviz.services import plans as svc
from stockviz.services.instruments import resolve_symbol
from stockviz.services.trading.books import resolve_book

router = APIRouter(prefix="/v1/plans", tags=["plans"])

SessionDep = Annotated[Session, Depends(get_session)]


def _owned(session: Session, plan_id: int, user_id: int) -> TradePlan:
    plan = session.get(TradePlan, plan_id)
    if plan is None or plan.user_id != user_id:
        raise svc.PlanNotFound(f"Plan {plan_id} not found")
    if (
        plan.replay_session_id is not None
        and plan.replay_session_id in svc.hidden_drill_session_ids(session, user_id)
    ):
        raise svc.PlanNotFound(f"Plan {plan_id} not found")
    return plan


def _paper(plan: TradePlan) -> None:
    if plan.source in ("replay", "drill"):
        where = "replay journal" if plan.source == "replay" else "drill's plan form"
        raise svc.PlanConflict(f"This plan belongs to a replay session: edit it in the {where}")


def _one(session: Session, plan: TradePlan) -> TradePlanOut:
    return svc.plan_outs(session, [plan])[0]


@router.get("", response_model=TradePlansOut)
def list_plans(
    session: SessionDep,
    user_id: UserIdDep,
    book: BookQuery = None,
    status_: Annotated[
        Literal["open", "active", "closed", "cancelled"] | None, Query(alias="status")
    ] = None,
    source: Literal["paper", "replay", "drill", "imported"] | None = None,
    setup_version_id: Annotated[int | None, Query(ge=1)] = None,
    ticker: Annotated[str | None, Query(min_length=1, max_length=16)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> TradePlansOut:
    stmt = select(TradePlan).where(col(TradePlan.user_id) == user_id)
    if book is not None:
        chosen = resolve_book(session, user_id, book)
        stmt = stmt.where(col(TradePlan.portfolio_id) == chosen.id)
    if status_ is not None:
        stmt = stmt.where(col(TradePlan.status) == status_)
    if source is not None:
        stmt = stmt.where(col(TradePlan.source) == source)
    if setup_version_id is not None:
        stmt = stmt.where(col(TradePlan.setup_version_id) == setup_version_id)
    if ticker is not None:
        instrument = resolve_symbol(session, ticker)
        if instrument is None:
            return TradePlansOut(plans=[], limit=MAX_PLANS_PER_USER)
        stmt = stmt.where(col(TradePlan.instrument_id) == instrument.id)
    hidden = svc.hidden_drill_session_ids(session, user_id)
    if hidden:
        stmt = stmt.where(
            col(TradePlan.replay_session_id).is_(None)
            | col(TradePlan.replay_session_id).not_in(sorted(hidden))
        )
    rows = list(
        session.exec(
            stmt.order_by(col(TradePlan.created_at).desc(), col(TradePlan.id).desc()).limit(limit)
        ).all()
    )
    return TradePlansOut(plans=svc.plan_outs(session, rows), limit=MAX_PLANS_PER_USER)


@router.post("", response_model=TradePlanOut, status_code=status.HTTP_201_CREATED)
def create_plan(
    body: TradePlanIn, session: SessionDep, user_id: UserIdDep, book: BookQuery = None
) -> TradePlanOut:
    portfolio = resolve_book(session, user_id, book, write=True)
    assert portfolio.id is not None
    instrument = resolve_symbol(session, body.ticker)
    if instrument is None or instrument.id is None:
        raise svc.PlanNotFound(f"Unknown symbol {body.ticker}")
    if instrument.asset_type == "index":
        raise svc.PlanError(f"{body.ticker.upper()} is an index: it can't be traded")
    entries: list[Trade] = []
    if body.link_open_position:
        entries = svc.open_position_entries(
            session, portfolio_id=portfolio.id, instrument_id=instrument.id
        )
        if not entries:
            raise svc.PlanError(f"This book holds no {body.ticker.upper()} to link the plan to")
        if any(t.trade_plan_id is not None for t in entries):
            raise svc.PlanConflict("That position already has a plan")
    plan = svc.new_paper_plan(
        session,
        user_id=user_id,
        book=portfolio,
        instrument_id=instrument.id,
        draft=body,
    )
    for trade in entries:
        svc.link_trade(session, plan, trade)
    session.commit()
    session.refresh(plan)
    return _one(session, plan)


@router.get("/{plan_id}", response_model=TradePlanOut)
def get_plan(plan_id: int, session: SessionDep, user_id: UserIdDep) -> TradePlanOut:
    return _one(session, _owned(session, plan_id, user_id))


@router.patch("/{plan_id}", response_model=TradePlanOut)
def patch_plan(
    plan_id: int, body: TradePlanPatch, session: SessionDep, user_id: UserIdDep
) -> TradePlanOut:
    plan = _owned(session, plan_id, user_id)
    _paper(plan)
    svc.check_references(session, user_id, body)
    if body.thesis_id is not None:
        thesis = session.get(Thesis, body.thesis_id)
        if thesis is not None and thesis.instrument_id != plan.instrument_id:
            raise svc.PlanError("The thesis is about another symbol")
    svc.apply_patch(plan, body)
    session.add(plan)
    session.commit()
    session.refresh(plan)
    return _one(session, plan)


@router.delete("/{plan_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_plan(plan_id: int, session: SessionDep, user_id: UserIdDep) -> Response:
    plan = _owned(session, plan_id, user_id)
    _paper(plan)
    if plan.frozen:
        raise svc.PlanConflict("A plan with a fill is part of your record: close it instead")
    # SQLite enforces no foreign keys: unlink pending orders here (SET NULL).
    for order in session.exec(
        select(PendingOrder).where(col(PendingOrder.trade_plan_id) == plan.id)
    ):
        order.trade_plan_id = None
        session.add(order)
    session.delete(plan)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
