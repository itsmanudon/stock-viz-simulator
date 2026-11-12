"""`/v1/screens` — saved screens per user (Phase 6.2).

A saved screen is a name and the screener URL's query string. Private to its
owner; names are unique per user. All endpoints need ``UserIdDep``.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, func, select

from stockviz._time import utcnow
from stockviz.auth import UserIdDep
from stockviz.db import get_session
from stockviz.models import SavedScreen
from stockviz.schemas import SavedScreenIn, SavedScreenOut

router = APIRouter(prefix="/v1/screens", tags=["screener"])

SessionDep = Annotated[Session, Depends(get_session)]

MAX_SCREENS_PER_USER = 50


def _out(row: SavedScreen) -> SavedScreenOut:
    assert row.id is not None
    return SavedScreenOut(
        id=row.id,
        name=row.name,
        query=row.query,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _clean(query: str) -> str:
    return query.lstrip("?").strip()


@router.get("", response_model=list[SavedScreenOut])
def list_screens(session: SessionDep, user_id: UserIdDep) -> list[SavedScreenOut]:
    rows = session.exec(
        select(SavedScreen)
        .where(col(SavedScreen.user_id) == user_id)
        .order_by(col(SavedScreen.name))
    ).all()
    return [_out(r) for r in rows]


@router.post("", response_model=SavedScreenOut, status_code=status.HTTP_201_CREATED)
def save_screen(body: SavedScreenIn, session: SessionDep, user_id: UserIdDep) -> SavedScreenOut:
    """Create a screen, or replace the query of the one with this name."""
    existing = session.exec(
        select(SavedScreen).where(
            col(SavedScreen.user_id) == user_id, col(SavedScreen.name) == body.name
        )
    ).first()
    if existing is not None:
        existing.query = _clean(body.query)
        existing.updated_at = utcnow()
        session.add(existing)
        session.commit()
        session.refresh(existing)
        return _out(existing)
    count = session.exec(
        select(func.count()).select_from(SavedScreen).where(col(SavedScreen.user_id) == user_id)
    ).one()
    if count >= MAX_SCREENS_PER_USER:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"At most {MAX_SCREENS_PER_USER} saved screens"
        )
    row = SavedScreen(user_id=user_id, name=body.name, query=_clean(body.query))
    session.add(row)
    try:
        session.commit()
    except IntegrityError as exc:  # a concurrent save of the same name
        session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "A screen with that name exists") from exc
    session.refresh(row)
    return _out(row)


@router.delete("/{screen_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_screen(screen_id: int, session: SessionDep, user_id: UserIdDep) -> None:
    row = session.get(SavedScreen, screen_id)
    if row is None or row.user_id != user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Screen {screen_id} not found")
    session.delete(row)
    session.commit()
