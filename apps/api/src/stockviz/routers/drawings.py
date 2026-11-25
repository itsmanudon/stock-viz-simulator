"""`/v1/drawings` (A3.2, M2.4): a user's chart drawings on one instrument.
Authed, private to the owner; another user's drawing is 404.

- ``GET ?ticker=`` -> ``{ticker, drawings, limit, first_bar, last_bar}``,
  oldest first.
- ``POST`` (201): ``{ticker, kind, points, style?, label?, locked?}``; 409
  past ``MAX_DRAWINGS_PER_INSTRUMENT`` per user and instrument.
- ``PATCH /{id}``: points, style, label (null clears), locked. A locked
  drawing takes only ``locked``.
- ``DELETE /{id}`` (204); a locked drawing is 409.

Validation per kind is ``services/drawings.py``.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlmodel import Session, col, select

from stockviz._time import utcnow
from stockviz.auth import UserIdDep
from stockviz.db import get_session
from stockviz.models.drawing import MAX_DRAWINGS_PER_INSTRUMENT, Drawing
from stockviz.schemas import DrawingIn, DrawingOut, DrawingPatch, DrawingsOut
from stockviz.services.drawings import (
    bar_range,
    count_for,
    drawing_out,
    points_json,
    points_of,
    validate_points,
)
from stockviz.services.instruments import resolve_symbol
from stockviz.services.theses import tickers_for

router = APIRouter(prefix="/v1/drawings", tags=["drawings"])

SessionDep = Annotated[Session, Depends(get_session)]


def _instrument_id(session: Session, ticker: str) -> tuple[int, str]:
    symbol = ticker.strip().upper()
    instrument = resolve_symbol(session, symbol)
    if instrument is None or instrument.id is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown symbol {symbol}")
    return instrument.id, symbol


def _owned(session: Session, drawing_id: int, user_id: int) -> Drawing:
    row = session.get(Drawing, drawing_id)
    if row is None or row.user_id != user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Drawing {drawing_id} not found")
    return row


def _ticker_of(session: Session, row: Drawing) -> str:
    return tickers_for(session, [row.instrument_id]).get(row.instrument_id, "")


@router.get("", response_model=DrawingsOut)
def list_drawings(
    session: SessionDep,
    user_id: UserIdDep,
    ticker: Annotated[str, Query(min_length=1, max_length=16)],
) -> DrawingsOut:
    instrument_id, symbol = _instrument_id(session, ticker)
    rows = session.exec(
        select(Drawing)
        .where(col(Drawing.user_id) == user_id, col(Drawing.instrument_id) == instrument_id)
        .order_by(col(Drawing.created_at), col(Drawing.id))
    ).all()
    first, last = bar_range(session, instrument_id, symbol)
    return DrawingsOut(
        ticker=symbol,
        drawings=[drawing_out(row, symbol) for row in rows],
        limit=MAX_DRAWINGS_PER_INSTRUMENT,
        first_bar=first,
        last_bar=last,
    )


@router.post("", response_model=DrawingOut, status_code=status.HTTP_201_CREATED)
def create_drawing(body: DrawingIn, session: SessionDep, user_id: UserIdDep) -> DrawingOut:
    instrument_id, symbol = _instrument_id(session, body.ticker)
    label = body.label.strip() if body.label and body.label.strip() else None
    first, last = bar_range(session, instrument_id, symbol)
    validate_points(body.kind, body.points, label, first, last)
    if count_for(session, user_id, instrument_id) >= MAX_DRAWINGS_PER_INSTRUMENT:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"At most {MAX_DRAWINGS_PER_INSTRUMENT} drawings on one symbol",
        )
    row = Drawing(
        user_id=user_id,
        instrument_id=instrument_id,
        kind=body.kind,
        points=points_json(body.points),
        style=body.style.model_dump(),
        label=label,
        locked=body.locked,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return drawing_out(row, symbol)


@router.patch("/{drawing_id}", response_model=DrawingOut)
def update_drawing(
    drawing_id: int, body: DrawingPatch, session: SessionDep, user_id: UserIdDep
) -> DrawingOut:
    row = _owned(session, drawing_id, user_id)
    sent = body.model_fields_set
    edits = sent - {"locked"}
    if row.locked and edits and body.locked is not False:
        raise HTTPException(status.HTTP_409_CONFLICT, "The drawing is locked; unlock it first")
    symbol = _ticker_of(session, row)
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
    points = points_of(row)
    if "points" in sent:
        if body.points is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "points cannot be null")
        points = body.points
    if {"points", "label"} & sent:
        first, last = bar_range(session, row.instrument_id, symbol)
        validate_points(row.kind, points, label, first, last)
        row.points = points_json(points)
        row.label = label
    row.updated_at = utcnow()
    session.add(row)
    session.commit()
    session.refresh(row)
    return drawing_out(row, symbol)


@router.delete("/{drawing_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_drawing(drawing_id: int, session: SessionDep, user_id: UserIdDep) -> Response:
    row = _owned(session, drawing_id, user_id)
    if row.locked:
        raise HTTPException(status.HTTP_409_CONFLICT, "The drawing is locked; unlock it first")
    session.delete(row)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
