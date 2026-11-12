"""Saved screens (Phase 6.2).

A screen is the screener's URL query string, stored under a name. The URL
stays the source of truth: opening a saved screen is opening its link, and a
screen can still be shared as a link without saving it.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, Text, UniqueConstraint
from sqlmodel import Field, SQLModel

from stockviz._time import utcnow


class SavedScreen(SQLModel, table=True):
    __tablename__ = "saved_screens"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_saved_screens_user_name"),)

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    name: str = Field(max_length=80)
    query: str = Field(sa_column=Column(Text, nullable=False))
    created_at: datetime = Field(default_factory=utcnow, nullable=False)
    updated_at: datetime = Field(default_factory=utcnow, nullable=False)
