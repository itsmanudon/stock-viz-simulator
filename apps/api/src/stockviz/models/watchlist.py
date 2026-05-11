"""User-curated watchlists."""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Field, SQLModel

from stockviz._time import utcnow


class Watchlist(SQLModel, table=True):
    __tablename__ = "watchlists"  # pyright: ignore[reportAssignmentType]

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    name: str = Field(max_length=128)
    created_at: datetime = Field(default_factory=utcnow, nullable=False)


class WatchlistItem(SQLModel, table=True):
    __tablename__ = "watchlist_items"  # pyright: ignore[reportAssignmentType]

    watchlist_id: int = Field(foreign_key="watchlists.id", primary_key=True)
    ticker: str = Field(foreign_key="symbols.ticker", primary_key=True, max_length=16)
    added_at: datetime = Field(default_factory=utcnow, nullable=False)
