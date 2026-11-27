"""A7.14 NSE index options from the owner's minute files, as daily summaries.

Revision ID: b7e2f4a6c8d1
Revises: a7d1c3e5f9b2
Create Date: 2026-11-27 12:00:00.000000

- ``fo_daily``: (underlying, series, day, option type, strike offset) -> the
  day's last minute (premium, IV, OI, spot) and summed volume.
- ``fo_files``: the owner's files loaded (SHA-256 unique, counts).

Additive. Written only into a local database (the loader's guard).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b7e2f4a6c8d1"
down_revision: str | None = "a7d1c3e5f9b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "fo_daily",
        sa.Column("underlying", sa.String(length=24), primary_key=True),
        sa.Column("series", sa.String(length=16), primary_key=True),
        sa.Column("day", sa.Date(), primary_key=True),
        sa.Column("option_type", sa.String(length=2), primary_key=True),
        sa.Column("strike_offset", sa.Integer(), primary_key=True),
        sa.Column("close", sa.Numeric(18, 4), nullable=False),
        sa.Column("iv", sa.Float(), nullable=True),
        sa.Column("oi", sa.BigInteger(), nullable=True),
        sa.Column("volume", sa.BigInteger(), nullable=False),
        sa.Column("spot", sa.Numeric(18, 4), nullable=False),
        sa.Column("last_minute", sa.String(length=8), nullable=False),
        sa.Column("minutes", sa.Integer(), nullable=False),
        sa.CheckConstraint("option_type IN ('CE', 'PE')", name="ck_fo_daily_option_type"),
    )
    op.create_table(
        "fo_files",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("series", sa.String(length=16), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("rows_total", sa.Integer(), nullable=False),
        sa.Column("rows_rejected", sa.Integer(), nullable=False),
        sa.Column("loaded_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("sha256"),
    )


def downgrade() -> None:
    op.drop_table("fo_files")
    op.drop_table("fo_daily")
