"""Write and read in-app notifications (Phase 7.2).

``notify`` stages a row in the caller's transaction and never commits, so a
notification exists exactly when the change it reports does. A repeated
``source_key`` is ignored: reruns of the nightly jobs add nothing.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import delete
from sqlmodel import Session, col, select

from stockviz._time import utcnow
from stockviz.models import Notification, NotificationCategory, Portfolio

RETENTION_DAYS = 180
"""Read notifications older than this are deleted by ``prune-events``."""


def notify(
    session: Session,
    *,
    user_id: int,
    category: NotificationCategory,
    title: str,
    body: str,
    source_key: str,
    link: str | None = None,
) -> Notification | None:
    """Stage one notification unless ``source_key`` exists. Does not commit."""
    if session.exec(select(Notification.id).where(Notification.source_key == source_key)).first():
        return None
    for pending in session.new:
        if isinstance(pending, Notification) and pending.source_key == source_key:
            return None
    row = Notification(
        user_id=user_id,
        category=category.value,
        title=title[:200],
        body=body[:1000],
        link=link,
        source_key=source_key[:160],
    )
    session.add(row)
    return row


def notify_portfolio(session: Session, portfolio_id: int | None, **kwargs) -> Notification | None:
    """:func:`notify` the owner of ``portfolio_id``."""
    portfolio = session.get(Portfolio, portfolio_id) if portfolio_id is not None else None
    if portfolio is None:
        return None
    return notify(session, user_id=portfolio.user_id, **kwargs)


def prune_read(session: Session, *, days: int = RETENTION_DAYS) -> int:
    """Delete read notifications older than ``days``. Commits."""
    cutoff = utcnow() - timedelta(days=days)
    result = session.exec(  # type: ignore[call-overload]
        delete(Notification).where(
            col(Notification.read_at).is_not(None), col(Notification.created_at) < cutoff
        )
    )
    session.commit()
    return int(result.rowcount or 0)
