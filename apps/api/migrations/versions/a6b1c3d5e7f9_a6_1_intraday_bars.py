"""A6.1 intraday bars (M2.2 foundation): intraday_files, intraday_bars.

Revision ID: a6b1c3d5e7f9
Revises: c9d2e4f6a8b1
Create Date: 2026-11-26 23:59:00.000000

- ``intraday_files``: provenance of each loaded file (name, SHA-256 unique,
  size, kind ``bulk_1m``/``bulk_1h``, instrument, the last load's counts).
- ``intraday_bars``: key (instrument_id, feed, interval, ts), ``ts`` the bar's
  open instant in naive UTC; OHLC ``Numeric(18, 6)``, volume, source,
  file_id, ingested_at, available_at. Range-partitioned by ``ts`` on
  PostgreSQL; the monthly partitions (``intraday_bars_yYYYYmMM``) are made by
  the writer when it first needs them, so the migration makes none.

Additive. The downgrade drops both tables with every partition: their rows
come only from the owner's local files (``stockviz.cli intraday-load``) and
reload from them.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a6b1c3d5e7f9"
down_revision: str | None = "c9d2e4f6a8b1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "intraday_files",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("instrument_id", sa.BigInteger(), nullable=False),
        sa.Column("rows_total", sa.Integer(), nullable=False),
        sa.Column("rows_accepted", sa.Integer(), nullable=False),
        sa.Column("rows_inserted", sa.Integer(), nullable=False),
        sa.Column("rows_off_session", sa.Integer(), nullable=False),
        sa.Column("rows_invalid", sa.Integer(), nullable=False),
        sa.Column("rows_duplicate", sa.Integer(), nullable=False),
        sa.Column("first_ts", sa.DateTime(), nullable=True),
        sa.Column("last_ts", sa.DateTime(), nullable=True),
        sa.Column("loaded_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("kind IN ('bulk_1m', 'bulk_1h')", name="ck_intraday_files_kind"),
        sa.ForeignKeyConstraint(["instrument_id"], ["instruments.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sha256"),
    )
    op.create_index(
        op.f("ix_intraday_files_instrument_id"), "intraday_files", ["instrument_id"], unique=False
    )
    op.create_table(
        "intraday_bars",
        sa.Column("instrument_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("feed", sa.String(length=8), nullable=False),
        sa.Column("interval", sa.String(length=4), nullable=False),
        sa.Column("ts", sa.DateTime(), nullable=False),
        sa.Column("open", sa.Numeric(18, 6), nullable=False),
        sa.Column("high", sa.Numeric(18, 6), nullable=False),
        sa.Column("low", sa.Numeric(18, 6), nullable=False),
        sa.Column("close", sa.Numeric(18, 6), nullable=False),
        sa.Column("volume", sa.BigInteger(), nullable=False),
        sa.Column("source", sa.String(length=24), nullable=False),
        sa.Column("file_id", sa.Integer(), nullable=True),
        sa.Column("ingested_at", sa.DateTime(), nullable=False),
        sa.Column("available_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("feed IN ('iex', 'sip', 'kite', 'file')", name="ck_intraday_bars_feed"),
        sa.CheckConstraint("interval IN ('1m', '60m')", name="ck_intraday_bars_interval"),
        sa.ForeignKeyConstraint(["instrument_id"], ["instruments.id"]),
        sa.ForeignKeyConstraint(["file_id"], ["intraday_files.id"]),
        sa.PrimaryKeyConstraint("instrument_id", "feed", "interval", "ts"),
        postgresql_partition_by="RANGE (ts)",
    )


def downgrade() -> None:
    op.drop_table("intraday_bars")  # drops every monthly partition with it
    op.drop_index(op.f("ix_intraday_files_instrument_id"), table_name="intraday_files")
    op.drop_table("intraday_files")
