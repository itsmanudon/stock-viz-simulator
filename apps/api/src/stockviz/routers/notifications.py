"""`/v1/notifications` — the notification centre (Phase 7.2).

In-app only (owner's choice for Phase 7). Every endpoint is the caller's own
rows through ``UserIdDep``.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, update
from sqlmodel import Session, col, select

from stockviz._time import utcnow
from stockviz.auth import UserIdDep
from stockviz.db import get_session
from stockviz.models import Notification, NotificationCategory
from stockviz.schemas import NotificationOut, UnreadCountOut

router = APIRouter(prefix="/v1/notifications", tags=["notifications"])

SessionDep = Annotated[Session, Depends(get_session)]


@router.get("", response_model=list[NotificationOut])
def list_notifications(
    session: SessionDep,
    user_id: UserIdDep,
    category: NotificationCategory | None = None,
    unread: bool = False,
    before_id: Annotated[int | None, Query(ge=1)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[Notification]:
    """Newest first. ``before_id`` pages back."""
    stmt = select(Notification).where(Notification.user_id == user_id)
    if category is not None:
        stmt = stmt.where(Notification.category == category.value)
    if unread:
        stmt = stmt.where(col(Notification.read_at).is_(None))
    if before_id is not None:
        stmt = stmt.where(col(Notification.id) < before_id)
    return list(session.exec(stmt.order_by(col(Notification.id).desc()).limit(limit)).all())


@router.get("/unread-count", response_model=UnreadCountOut)
def unread_count(session: SessionDep, user_id: UserIdDep) -> UnreadCountOut:
    count = session.exec(
        select(func.count())  # type: ignore[call-overload]
        .select_from(Notification)
        .where(Notification.user_id == user_id, col(Notification.read_at).is_(None))
    ).one()
    return UnreadCountOut(unread=int(count or 0))


@router.post("/{notification_id}/read", response_model=NotificationOut)
def mark_read(notification_id: int, session: SessionDep, user_id: UserIdDep) -> Notification:
    row = session.get(Notification, notification_id)
    if row is None or row.user_id != user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Notification not found")
    if row.read_at is None:
        row.read_at = utcnow()
        session.add(row)
        session.commit()
        session.refresh(row)
    return row


@router.post("/read-all", response_model=UnreadCountOut)
def mark_all_read(session: SessionDep, user_id: UserIdDep) -> UnreadCountOut:
    session.exec(  # type: ignore[call-overload]
        update(Notification)
        .where(col(Notification.user_id) == user_id, col(Notification.read_at).is_(None))
        .values(read_at=utcnow())
    )
    session.commit()
    return UnreadCountOut(unread=0)
