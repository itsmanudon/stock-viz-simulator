"""User-curated watchlists (A2.5, M4.6: many per user).

A user has any number of named lists (``watchlists``), each with a colour tag
from a fixed palette and a position for ordering. Exactly one is the user's
default (``is_default``, a partial unique index): the old single-list routes
(``/v1/watchlist``), the stock page's one-click star and the dashboard widget
use it. Items carry a free-text ``note`` and short ``tags``. ``column_sets``
holds saved, ordered metric columns per user; a list can remember one.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Column, ForeignKey, Index, Integer, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from stockviz._time import utcnow
from stockviz.models.instrument import instrument_id_column

_JSON = JSON().with_variant(JSONB(), "postgresql")

WATCHLIST_COLOURS = ("aqua", "blue", "violet", "pink", "amber", "lime", "slate")
"""The colour tags, each an Aurora list token in the web (``--list-<name>``)."""

DEFAULT_WATCHLIST_NAME = "Default"
NOTE_MAX = 2000
TAGS_MAX = 10
TAG_MAX_LENGTH = 24


class ColumnSet(SQLModel, table=True):
    __tablename__ = "column_sets"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_column_sets_user_name"),)

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    name: str = Field(max_length=64)
    # Ordered metric keys from services/watchlists.COLUMN_KEYS.
    columns: list[str] = Field(default_factory=list, sa_column=Column(_JSON, nullable=False))
    created_at: datetime = Field(default_factory=utcnow, nullable=False)
    updated_at: datetime = Field(default_factory=utcnow, nullable=False)


class Watchlist(SQLModel, table=True):
    __tablename__ = "watchlists"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_watchlists_user_name"),
        Index(
            "uq_watchlists_user_default",
            "user_id",
            unique=True,
            postgresql_where=text("is_default"),
            sqlite_where=text("is_default"),
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    name: str = Field(max_length=128)
    colour: str = Field(default="aqua", max_length=16)
    position: int = Field(default=0)
    is_default: bool = Field(default=False)
    column_set_id: int | None = Field(
        default=None,
        sa_column=Column(Integer, ForeignKey("column_sets.id", ondelete="SET NULL"), nullable=True),
    )
    created_at: datetime = Field(default_factory=utcnow, nullable=False)


class WatchlistItem(SQLModel, table=True):
    __tablename__ = "watchlist_items"  # pyright: ignore[reportAssignmentType]

    watchlist_id: int = Field(foreign_key="watchlists.id", primary_key=True)
    ticker: str = Field(foreign_key="symbols.ticker", max_length=16)
    # Phase 4.6b: keyed by (watchlist, instrument).
    instrument_id: int | None = Field(
        default=None, sa_column=instrument_id_column(primary_key=True)
    )
    added_at: datetime = Field(default_factory=utcnow, nullable=False)
    note: str | None = Field(default=None, sa_column=Column(String(NOTE_MAX), nullable=True))
    tags: list[str] = Field(default_factory=list, sa_column=Column(_JSON, nullable=False))
