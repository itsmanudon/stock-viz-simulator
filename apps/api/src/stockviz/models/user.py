"""User account.

Phase 2 keeps this thin: the API doesn't issue tokens yet. Phase 3 wires
NextAuth (Auth.js) and the web app becomes the source of truth for sessions;
this table stays as the canonical user row that portfolios/watchlists FK to.
"""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Field, SQLModel

from stockviz._time import utcnow


class User(SQLModel, table=True):
    __tablename__ = "users"  # pyright: ignore[reportAssignmentType]

    id: int | None = Field(default=None, primary_key=True)
    email: str = Field(unique=True, index=True, max_length=320)
    name: str | None = None
    image: str | None = Field(default=None, max_length=1024)
    # Bcrypt hash for credentials-provider auth. NULL means the account was
    # created via OAuth (Phase 3 has credentials only, so right now NULL only
    # happens for rows seeded outside of signup).
    password_hash: str | None = Field(default=None, max_length=255)
    public_profile: bool = Field(default=False, nullable=False)
    # ISO-4217 currency the portfolio totals are rendered in on the UI. The
    # underlying cash balance stays USD-base; conversion happens at read time.
    display_currency: str = Field(default="USD", max_length=3, nullable=False)
    created_at: datetime = Field(default_factory=utcnow, nullable=False)
