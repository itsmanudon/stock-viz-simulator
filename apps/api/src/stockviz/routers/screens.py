"""`/v1/screens` — saved screens per user (Phase 6.2).

A saved screen is a name and the screener URL's query string. Private to its
owner; names are unique per user. All endpoints need ``UserIdDep``.

A2.2: a screen may also name a ``setup_version_id`` (the user's own setup's
or a preset's; anything else is 404). Screens saved before keep working:
their query alone is the screen.

A2.3: ``notify_on_change`` subscribes the screen to the nightly
``screen-runs`` diff (a notification when its rule's members change). It
needs a ``setup_version_id`` (400 otherwise). ``PATCH /{id}`` flips it.
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
from stockviz.schemas import SavedScreenIn, SavedScreenOut, SavedScreenPatch
from stockviz.services.setups import store as setups

router = APIRouter(prefix="/v1/screens", tags=["screener"])

SessionDep = Annotated[Session, Depends(get_session)]

MAX_SCREENS_PER_USER = 50


def _out(row: SavedScreen) -> SavedScreenOut:
    assert row.id is not None
    return SavedScreenOut(
        id=row.id,
        name=row.name,
        query=row.query,
        setup_version_id=row.setup_version_id,
        notify_on_change=row.notify_on_change,
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
    """Create a screen, or replace the query (and setup version) of the one with this name."""
    if body.setup_version_id is not None:
        try:
            setups.visible_version(session, body.setup_version_id, user_id)
        except setups.SetupNotFound as exc:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, f"Setup version {body.setup_version_id} not found"
            ) from exc
    existing = session.exec(
        select(SavedScreen).where(
            col(SavedScreen.user_id) == user_id, col(SavedScreen.name) == body.name
        )
    ).first()
    notify = body.notify_on_change
    if notify is None:
        notify = existing.notify_on_change if existing is not None else False
    if notify and body.setup_version_id is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Change notifications need a saved rule (setup version)"
        )
    if existing is not None:
        existing.query = _clean(body.query)
        existing.setup_version_id = body.setup_version_id
        existing.notify_on_change = notify
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
    row = SavedScreen(
        user_id=user_id,
        name=body.name,
        query=_clean(body.query),
        setup_version_id=body.setup_version_id,
        notify_on_change=notify,
    )
    session.add(row)
    try:
        session.commit()
    except IntegrityError as exc:  # a concurrent save of the same name
        session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "A screen with that name exists") from exc
    session.refresh(row)
    return _out(row)


@router.patch("/{screen_id}", response_model=SavedScreenOut)
def patch_screen(
    screen_id: int, body: SavedScreenPatch, session: SessionDep, user_id: UserIdDep
) -> SavedScreenOut:
    """Turn the nightly change notification on or off (A2.3)."""
    row = session.get(SavedScreen, screen_id)
    if row is None or row.user_id != user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Screen {screen_id} not found")
    if body.notify_on_change and row.setup_version_id is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Change notifications need a saved rule (setup version)"
        )
    row.notify_on_change = body.notify_on_change
    row.updated_at = utcnow()
    session.add(row)
    session.commit()
    session.refresh(row)
    return _out(row)


@router.delete("/{screen_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_screen(screen_id: int, session: SessionDep, user_id: UserIdDep) -> None:
    row = session.get(SavedScreen, screen_id)
    if row is None or row.user_id != user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Screen {screen_id} not found")
    session.delete(row)
    session.commit()
