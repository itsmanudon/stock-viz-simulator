"""Classroom cohorts (A10.2, M12.1, M12.2), authed.

- `POST /v1/cohorts` (instructor), `GET /v1/cohorts`, `GET /v1/cohorts/{id}`
- `POST /v1/cohorts/join` `{code, consent}` (422 without consent)
- `DELETE /v1/cohorts/{id}/membership` (a member leaves)
- `POST /v1/cohorts/{id}/assignments` (owner)
- `POST /v1/assignments/{id}/start` (member: makes or returns their deck)
- `GET /v1/cohorts/{id}/gradebook` (owner): process counts only

Another user's cohort is 404, as is a member asking for the gradebook.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, col, func, select

from stockviz.auth import UserIdDep
from stockviz.db import get_session
from stockviz.models import AssignmentDeck, Cohort, CohortAssignment, CohortMember
from stockviz.schemas import (
    CohortAssignmentIn,
    CohortAssignmentOut,
    CohortIn,
    CohortJoinIn,
    CohortOut,
    CohortStartOut,
    GradebookCellOut,
    GradebookOut,
    GradebookRowOut,
)
from stockviz.services import classroom as svc
from stockviz.services.backtest.strategy_run import StrategyNeedsUser, StrategyNotFound
from stockviz.services.drills import decks
from stockviz.services.dsl import RuleError
from stockviz.services.replay import ReplayLagError, ReplayRangeError
from stockviz.services.scan_event_study import ScanStudyError
from stockviz.services.setups.rules import error_out

router = APIRouter(tags=["classroom"])

SessionDep = Annotated[Session, Depends(get_session)]

RUBRIC = (
    "Meets the rubric when every drill is revealed and at least the assignment's share of "
    "traded drills followed the plan (entry, stop and size checks)."
)
PRIVACY = "Process counts only. P&L, R, fills, books, symbols and dates never reach the instructor."


def _errors(exc: Exception) -> HTTPException:
    if isinstance(exc, svc.ClassroomNotFound):
        return HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    if isinstance(exc, svc.ClassroomConflict | decks.DrillConflict):
        return HTTPException(status.HTTP_409_CONFLICT, str(exc))
    if isinstance(exc, svc.ClassroomError):
        return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))
    if isinstance(exc, StrategyNotFound):
        return HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    if isinstance(exc, StrategyNeedsUser):
        return HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc))
    if isinstance(exc, RuleError):
        return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, error_out(exc).model_dump())
    return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


ERRORS = (
    svc.ClassroomNotFound,
    svc.ClassroomConflict,
    svc.ClassroomError,
    decks.DrillConflict,
    decks.DrillError,
    StrategyNotFound,
    StrategyNeedsUser,
    RuleError,
    ScanStudyError,
    ReplayRangeError,
    ReplayLagError,
)


def _assignment_out(
    session: Session, a: CohortAssignment, user_id: int | None
) -> CohortAssignmentOut:
    assert a.id is not None
    link = session.get(AssignmentDeck, (a.id, user_id)) if user_id is not None else None
    rule = a.recipe.get("rule", {})
    return CohortAssignmentOut(
        id=a.id,
        title=a.title,
        min_followed_pct=a.min_followed_pct,
        due_on=a.due_on,
        rule=str(rule.get("rule") or f"setup version {rule.get('setup_version_id')}"),
        k=int(a.recipe.get("k", 10)),
        seed=a.recipe.get("seed"),
        created_at=a.created_at,
        my_deck_id=link.deck_id if link else None,
    )


def _cohort_out(session: Session, cohort: Cohort, role: str, user_id: int) -> CohortOut:
    assert cohort.id is not None
    members = session.exec(
        select(func.count())
        .select_from(CohortMember)
        .where(col(CohortMember.cohort_id) == cohort.id)
    ).one()
    assignments = session.exec(
        select(CohortAssignment)
        .where(CohortAssignment.cohort_id == cohort.id)
        .order_by(col(CohortAssignment.id))
    ).all()
    return CohortOut(
        id=cohort.id,
        name=cohort.name,
        role=role,  # pyright: ignore[reportArgumentType]
        invite_code=cohort.invite_code if role == "owner" else None,
        members=members,
        assignments=[
            _assignment_out(session, a, user_id if role == "member" else None) for a in assignments
        ],
        created_at=cohort.created_at,
        consent_text=svc.CONSENT_TEXT,
    )


@router.post("/v1/cohorts", response_model=CohortOut, status_code=201)
def create_cohort(body: CohortIn, session: SessionDep, user_id: UserIdDep) -> CohortOut:
    try:
        cohort = svc.create_cohort(session, user_id, body.name)
    except ERRORS as exc:
        raise _errors(exc) from exc
    return _cohort_out(session, cohort, "owner", user_id)


@router.get("/v1/cohorts", response_model=list[CohortOut])
def list_cohorts(session: SessionDep, user_id: UserIdDep) -> list[CohortOut]:
    owned = session.exec(select(Cohort).where(Cohort.owner_id == user_id)).all()
    joined = session.exec(
        select(Cohort)
        .join(CohortMember, col(CohortMember.cohort_id) == col(Cohort.id))
        .where(CohortMember.user_id == user_id)
    ).all()
    return [_cohort_out(session, c, "owner", user_id) for c in owned] + [
        _cohort_out(session, c, "member", user_id) for c in joined
    ]


@router.get("/v1/cohorts/{cohort_id}", response_model=CohortOut)
def get_cohort(cohort_id: int, session: SessionDep, user_id: UserIdDep) -> CohortOut:
    try:
        cohort, role = svc.visible_cohort(session, cohort_id, user_id)
    except ERRORS as exc:
        raise _errors(exc) from exc
    return _cohort_out(session, cohort, role, user_id)


@router.post("/v1/cohorts/join", response_model=CohortOut)
def join_cohort(body: CohortJoinIn, session: SessionDep, user_id: UserIdDep) -> CohortOut:
    try:
        cohort = svc.join(session, user_id, body.code, body.consent)
    except ERRORS as exc:
        raise _errors(exc) from exc
    return _cohort_out(session, cohort, "member", user_id)


@router.delete("/v1/cohorts/{cohort_id}/membership", status_code=204)
def leave_cohort(cohort_id: int, session: SessionDep, user_id: UserIdDep) -> None:
    try:
        svc.leave(session, cohort_id, user_id)
    except ERRORS as exc:
        raise _errors(exc) from exc


@router.post(
    "/v1/cohorts/{cohort_id}/assignments", response_model=CohortAssignmentOut, status_code=201
)
def add_assignment(
    cohort_id: int, body: CohortAssignmentIn, session: SessionDep, user_id: UserIdDep
) -> CohortAssignmentOut:
    try:
        cohort = svc.owned_cohort(session, cohort_id, user_id)
        a = svc.add_assignment(
            session, cohort, body.title, body.deck, body.min_followed_pct, body.due_on
        )
    except ERRORS as exc:
        raise _errors(exc) from exc
    return _assignment_out(session, a, None)


@router.post("/v1/assignments/{assignment_id}/start", response_model=CohortStartOut)
def start_assignment(assignment_id: int, session: SessionDep, user_id: UserIdDep) -> CohortStartOut:
    try:
        link, created = svc.start(session, assignment_id, user_id)
    except ERRORS as exc:
        raise _errors(exc) from exc
    return CohortStartOut(assignment_id=assignment_id, deck_id=link.deck_id, created=created)


@router.get("/v1/cohorts/{cohort_id}/gradebook", response_model=GradebookOut)
def gradebook(cohort_id: int, session: SessionDep, user_id: UserIdDep) -> GradebookOut:
    try:
        cohort = svc.owned_cohort(session, cohort_id, user_id)
    except ERRORS as exc:
        raise _errors(exc) from exc
    assignments, rows = svc.gradebook(session, cohort)
    assert cohort.id is not None
    return GradebookOut(
        cohort_id=cohort.id,
        assignments=[_assignment_out(session, a, None) for a in assignments],
        rows=[
            GradebookRowOut(
                user_id=r.user_id,
                name=r.name,
                joined_at=r.joined_at,
                cells=[GradebookCellOut(**asdict(c)) for c in r.cells],  # pyright: ignore[reportArgumentType]
            )
            for r in rows
        ],
        rubric=RUBRIC,
        privacy=PRIVACY,
    )
