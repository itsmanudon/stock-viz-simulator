"""Per-ticker user comments with threaded replies.

One row = one comment. ``parent_id`` is null for a top-level post and the
parent comment's id for a reply. Replies inherit their parent's ticker via
the application layer (we don't enforce the parent.ticker == child.ticker
invariant in the DB; the router rejects mismatches).

Hard-deletes only — there's no "edited"/"soft-deleted" state in v1.
"""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Field, SQLModel

from stockviz._time import utcnow


class Comment(SQLModel, table=True):
    __tablename__ = "comments"  # pyright: ignore[reportAssignmentType]

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    ticker: str = Field(foreign_key="symbols.ticker", index=True, max_length=16)
    body: str = Field(max_length=2000)
    parent_id: int | None = Field(default=None, foreign_key="comments.id", index=True)
    created_at: datetime = Field(default_factory=utcnow, nullable=False, index=True)
