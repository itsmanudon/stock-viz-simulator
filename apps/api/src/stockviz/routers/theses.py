"""`/v1/theses` (A2.2): a written view on one instrument, with an optional kill
rule in the Rule DSL. Authed, private to the owner.

- ``GET ""`` (``status=open|invalidated|closed``), ``POST ""``.
- ``PATCH /{id}``: title, body or kill rule while the thesis is open (409
  after). ``kill_rule: null`` removes it.
- ``POST /{id}/close``: ``closed`` or ``invalidated``; final.

The kill rule must compile (422 with line and column). A7.5: it is judged
nightly as a linked rule alert (``services/thesis_kill.py``). Before A7.5 nothing evaluated it
yet: that is A2.3 / A5.
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel import Session, col, func, select

from stockviz.auth import UserIdDep
from stockviz.db import get_session
from stockviz.models.setup import Thesis
from stockviz.schemas import ThesisCloseIn, ThesisIn, ThesisOut, ThesisPatch
from stockviz.services.instruments import resolve_symbol
from stockviz.services.setups.rules import compile_or_422
from stockviz.services.theses import (
    MAX_THESES_PER_USER,
    list_theses,
    thesis_out,
    tickers_for,
    touch,
)
from stockviz.services.thesis_kill import kill_state, sync_kill_alert

router = APIRouter(prefix="/v1/theses", tags=["theses"])

SessionDep = Annotated[Session, Depends(get_session)]


def _out(session: Session, row: Thesis) -> ThesisOut:
    ticker = tickers_for(session, [row.instrument_id]).get(row.instrument_id)
    return thesis_out(row, ticker, kill_state(session, row))


def _owned(session: Session, thesis_id: int, user_id: int) -> Thesis:
    row = session.get(Thesis, thesis_id)
    if row is None or row.user_id != user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Thesis {thesis_id} not found")
    return row


@router.get("", response_model=list[ThesisOut])
def get_theses(
    session: SessionDep,
    user_id: UserIdDep,
    status_: Annotated[
        Literal["open", "invalidated", "closed"] | None, Query(alias="status")
    ] = None,
) -> list[ThesisOut]:
    return list_theses(session, user_id, status_)


@router.post("", response_model=ThesisOut, status_code=status.HTTP_201_CREATED)
def create_thesis(body: ThesisIn, session: SessionDep, user_id: UserIdDep) -> ThesisOut:
    instrument = resolve_symbol(session, body.ticker)
    if instrument is None or instrument.id is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown symbol {body.ticker}")
    count = session.exec(
        select(func.count()).select_from(Thesis).where(col(Thesis.user_id) == user_id)
    ).one()
    if count >= MAX_THESES_PER_USER:
        raise HTTPException(status.HTTP_409_CONFLICT, f"At most {MAX_THESES_PER_USER} theses")
    rule = compile_or_422(body.kill_rule) if body.kill_rule else None
    row = Thesis(
        user_id=user_id,
        instrument_id=instrument.id,
        title=body.title.strip(),
        body=body.body,
        kill_rule_text=rule.text if rule else None,
        kill_rule_hash=rule.hash if rule else None,
    )
    session.add(row)
    session.flush()
    sync_kill_alert(session, row)  # A7.5: the kill switch follows the rule and status
    session.commit()
    session.refresh(row)
    return _out(session, row)


@router.patch("/{thesis_id}", response_model=ThesisOut)
def update_thesis(
    thesis_id: int, body: ThesisPatch, session: SessionDep, user_id: UserIdDep
) -> ThesisOut:
    row = _owned(session, thesis_id, user_id)
    if row.status != "open":
        raise HTTPException(status.HTTP_409_CONFLICT, f"The thesis is {row.status}")
    sent = body.model_fields_set
    if "title" in sent:
        if body.title is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "title cannot be empty")
        row.title = body.title.strip()
    if "body" in sent:
        if body.body is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "body cannot be empty")
        row.body = body.body
    if "kill_rule" in sent:
        rule = compile_or_422(body.kill_rule) if body.kill_rule else None
        row.kill_rule_text = rule.text if rule else None
        row.kill_rule_hash = rule.hash if rule else None
    touch(row)
    session.add(row)
    session.flush()
    sync_kill_alert(session, row)  # A7.5: the kill switch follows the rule and status
    session.commit()
    session.refresh(row)
    return _out(session, row)


@router.post("/{thesis_id}/close", response_model=ThesisOut)
def close_thesis(
    thesis_id: int,
    session: SessionDep,
    user_id: UserIdDep,
    body: ThesisCloseIn | None = None,
) -> ThesisOut:
    row = _owned(session, thesis_id, user_id)
    if row.status != "open":
        raise HTTPException(status.HTTP_409_CONFLICT, f"The thesis is already {row.status}")
    row.status = (body or ThesisCloseIn()).status
    touch(row)
    session.add(row)
    session.flush()
    sync_kill_alert(session, row)  # A7.5: the kill switch follows the rule and status
    session.commit()
    session.refresh(row)
    return _out(session, row)
