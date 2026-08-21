"""`/v1/symbols/{ticker}/comments` and `/v1/comments/{id}`.

Per-ticker discussion threads with one level of nested replies.

- ``GET /v1/symbols/{ticker}/comments`` (public) — paginated, newest-first
  top-level comments, each with its immediate ``replies`` inlined.
- ``POST /v1/symbols/{ticker}/comments`` (auth) — create a top-level comment
  or a reply (when ``parent_id`` is set). Rate-limited to 5 posts/minute
  per user via a DB count of recent rows — this gives accurate per-user
  enforcement that doesn't depend on the slowapi IP-based limiter (every
  caller is the Next.js server, so per-IP limiting would be global).
- ``DELETE /v1/comments/{id}`` (auth) — delete one's own comment. Returns
  404 (not 403) when the comment belongs to someone else so we don't leak
  existence to other users.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlmodel import Session, select

from stockviz._time import utcnow
from stockviz.auth import UserIdDep
from stockviz.db import get_session
from stockviz.models import Comment, Symbol, User
from stockviz.schemas import CommentIn, CommentOut

router = APIRouter(tags=["comments"])

SessionDep = Annotated[Session, Depends(get_session)]

MAX_COMMENT_LENGTH = 2000
"""Schema/db cap is 2000; we check it before insert to give a friendlier 400."""

RATE_LIMIT_WINDOW_SECONDS = 60
RATE_LIMIT_MAX_POSTS = 5


def _to_out(comment: Comment, *, user_name: str | None, replies: list[CommentOut]) -> CommentOut:
    return CommentOut(
        id=comment.id,  # type: ignore[arg-type]
        user_id=comment.user_id,
        user_name=user_name,
        ticker=comment.ticker,
        body=comment.body,
        parent_id=comment.parent_id,
        created_at=comment.created_at,
        replies=replies,
    )


def _user_name_map(session: Session, user_ids: list[int]) -> dict[int, str | None]:
    if not user_ids:
        return {}
    rows = list(session.exec(select(User).where(User.id.in_(user_ids))))  # type: ignore[attr-defined]
    return {u.id: u.name for u in rows if u.id is not None}


@router.get("/v1/symbols/{ticker}/comments", response_model=list[CommentOut])
def list_comments(
    ticker: str,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[CommentOut]:
    ticker = ticker.upper()
    if session.get(Symbol, ticker) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Symbol {ticker!r} not found")

    top_level = list(
        session.exec(
            select(Comment)
            .where(Comment.ticker == ticker, Comment.parent_id.is_(None))  # type: ignore[union-attr]
            .order_by(Comment.created_at.desc())  # type: ignore[attr-defined]
            .offset(offset)
            .limit(limit)
        )
    )
    parent_ids = [c.id for c in top_level if c.id is not None]
    children_by_parent: dict[int, list[Comment]] = {pid: [] for pid in parent_ids}
    if parent_ids:
        children = list(
            session.exec(
                select(Comment)
                .where(Comment.parent_id.in_(parent_ids))  # type: ignore[attr-defined]
                .order_by(Comment.created_at.asc())  # type: ignore[attr-defined]
            )
        )
        for child in children:
            if child.parent_id is not None:
                children_by_parent[child.parent_id].append(child)

    all_user_ids = {c.user_id for c in top_level}
    for replies in children_by_parent.values():
        all_user_ids.update(r.user_id for r in replies)
    names = _user_name_map(session, list(all_user_ids))

    return [
        _to_out(
            c,
            user_name=names.get(c.user_id),
            replies=[
                _to_out(child, user_name=names.get(child.user_id), replies=[])
                for child in children_by_parent.get(c.id or -1, [])
            ],
        )
        for c in top_level
    ]


@router.post(
    "/v1/symbols/{ticker}/comments",
    response_model=CommentOut,
    status_code=status.HTTP_201_CREATED,
)
def create_comment(
    ticker: str,
    body: CommentIn,
    session: SessionDep,
    user_id: UserIdDep,
) -> CommentOut:
    ticker = ticker.upper()
    if session.get(Symbol, ticker) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Symbol {ticker!r} not found")

    trimmed = body.body.strip()
    if not trimmed:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "body must not be empty")
    if len(trimmed) > MAX_COMMENT_LENGTH:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"body must be at most {MAX_COMMENT_LENGTH} characters",
        )

    if body.parent_id is not None:
        parent = session.get(Comment, body.parent_id)
        if parent is None or parent.ticker != ticker:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Parent comment not found")
        if parent.parent_id is not None:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Replies to replies are not supported — reply to the top-level comment instead",
            )

    # Per-user rate limit: count this user's posts in the trailing 60s.
    # COUNT(*) rather than materializing the rows just to call len() on them.
    cutoff = utcnow() - timedelta(seconds=RATE_LIMIT_WINDOW_SECONDS)
    recent_count = (
        session.exec(
            select(func.count())  # type: ignore[call-overload]
            .select_from(Comment)
            .where(
                Comment.user_id == user_id,
                Comment.created_at >= cutoff,
            )
        ).one()
        or 0
    )
    if recent_count >= RATE_LIMIT_MAX_POSTS:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"Rate limit: at most {RATE_LIMIT_MAX_POSTS} comments per minute",
        )

    comment = Comment(
        user_id=user_id,
        ticker=ticker,
        body=trimmed,
        parent_id=body.parent_id,
    )
    session.add(comment)
    session.commit()
    session.refresh(comment)

    author = session.get(User, user_id)
    return _to_out(comment, user_name=author.name if author else None, replies=[])


@router.delete("/v1/comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_comment(comment_id: int, session: SessionDep, user_id: UserIdDep) -> None:
    comment = session.get(Comment, comment_id)
    # 404 on both missing and not-owned so we don't reveal existence.
    if comment is None or comment.user_id != user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Comment not found")

    # Cascade: when deleting a top-level comment, drop its replies too so we
    # don't leave orphan rows pointing at a vanished parent_id.
    if comment.parent_id is None:
        replies = list(session.exec(select(Comment).where(Comment.parent_id == comment_id)))
        for r in replies:
            session.delete(r)
    session.delete(comment)
    session.commit()
