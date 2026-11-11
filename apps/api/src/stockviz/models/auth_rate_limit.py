"""Sign-in and sign-up attempt counters (audit OP-8).

Written only by the Next.js server actions (``apps/web/lib/rate-limit.ts``)
through its own Postgres pool; the API owns the table so Alembic owns the
schema. They used to live in the web process's memory, so they reset whenever
the web service slept and were not shared between instances. One row per
counted key (``login:email:<address>``, ``login:ip:<address>``,
``signup:ip:<address>``) in a fixed window. ``prune-events`` deletes rows
whose window ended more than a day ago.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, DateTime
from sqlmodel import Field, SQLModel


class AuthRateLimit(SQLModel, table=True):
    __tablename__ = "auth_rate_limits"  # pyright: ignore[reportAssignmentType]

    key: str = Field(primary_key=True, max_length=400)
    count: int = Field(nullable=False)
    # timestamptz: the web side compares it with now() in SQL only.
    reset_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
