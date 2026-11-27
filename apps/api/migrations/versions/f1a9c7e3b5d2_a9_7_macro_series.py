"""A9.7 macro series from FRED.

Revision ID: f1a9c7e3b5d2
Revises: e9a4b6c8d0f3
Create Date: 2026-11-27 09:00:00.000000

- ``macro_series``: one provider series (FRED id), its metadata and when it
  was last fetched.
- ``macro_observations``: (series, date) -> value; a null value is a date the
  provider lists without a number.

Additive. The downgrade drops both tables (the data is refetchable).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f1a9c7e3b5d2"
down_revision: str | None = "e9a4b6c8d0f3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "macro_series",
        sa.Column("series_id", sa.String(length=40), primary_key=True),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("units", sa.String(length=120), nullable=False),
        sa.Column("frequency", sa.String(length=40), nullable=False),
        sa.Column("observation_start", sa.Date(), nullable=True),
        sa.Column("observation_end", sa.Date(), nullable=True),
        sa.Column("provider_updated", sa.String(length=40), nullable=True),
        sa.Column("fetched_at", sa.DateTime(), nullable=True),
    )
    op.create_table(
        "macro_observations",
        sa.Column("series_id", sa.String(length=40), primary_key=True),
        sa.Column("obs_date", sa.Date(), primary_key=True),
        sa.Column("value", sa.Numeric(20, 6), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("macro_observations")
    op.drop_table("macro_series")
