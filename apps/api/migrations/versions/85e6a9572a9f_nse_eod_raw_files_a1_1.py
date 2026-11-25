"""NSE raw files and end-of-day rows (A1.1)

Revision ID: 85e6a9572a9f
Revises: ea0040711437
Create Date: 2026-11-25 20:38:51.843300

Additive only. ``data_files`` records each raw NSE file handed to
``stockviz.cli nse-load --apply`` (source, session, SHA-256 unique, size,
archive path, parse status and counts; never the contents). ``eod_raw``
holds the cash bhavcopy as published, ``eod_extras`` the delivery figures
from ``sec_bhavdata_full``; both keyed by (instrument, session, series), with
no ticker column and so no identity trigger. The ``isin`` identifier scheme
needs no schema change. The downgrade drops the three tables.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "85e6a9572a9f"
down_revision: str | None = "ea0040711437"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "data_files",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("trading_date", sa.Date(), nullable=True),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("archived_path", sa.String(length=512), nullable=False),
        sa.Column("received_at", sa.DateTime(), nullable=False),
        sa.Column("parse_status", sa.String(length=16), nullable=False),
        sa.Column("rows_total", sa.Integer(), nullable=False),
        sa.Column("rows_loaded", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "parse_status IN ('parsed', 'date_mismatch', 'unrecognised', 'failed')",
            name="ck_data_files_parse_status",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sha256"),
    )
    op.create_index(op.f("ix_data_files_source"), "data_files", ["source"], unique=False)
    op.create_index(
        op.f("ix_data_files_trading_date"), "data_files", ["trading_date"], unique=False
    )
    op.create_table(
        "eod_extras",
        sa.Column(
            "instrument_id",
            sa.BigInteger(),
            autoincrement=False,
            nullable=False,
        ),
        sa.Column("session_date", sa.Date(), nullable=False),
        sa.Column("series", sa.String(length=4), nullable=False),
        sa.Column("deliverable_qty", sa.BigInteger(), nullable=True),
        sa.Column("delivery_pct", sa.Numeric(precision=7, scale=2), nullable=True),
        sa.Column("data_file_id", sa.BigInteger(), nullable=False),
        sa.Column("loaded_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["data_file_id"],
            ["data_files.id"],
        ),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["instruments.id"],
        ),
        sa.PrimaryKeyConstraint("instrument_id", "session_date", "series"),
    )
    op.create_index(
        op.f("ix_eod_extras_data_file_id"), "eod_extras", ["data_file_id"], unique=False
    )
    op.create_index(
        op.f("ix_eod_extras_session_date"), "eod_extras", ["session_date"], unique=False
    )
    op.create_table(
        "eod_raw",
        sa.Column(
            "instrument_id",
            sa.BigInteger(),
            autoincrement=False,
            nullable=False,
        ),
        sa.Column("session_date", sa.Date(), nullable=False),
        sa.Column("series", sa.String(length=4), nullable=False),
        sa.Column("open", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("high", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("low", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("close", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("last", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column("prev_close", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column("volume", sa.BigInteger(), nullable=False),
        sa.Column("turnover", sa.Numeric(precision=24, scale=4), nullable=True),
        sa.Column("trades", sa.Integer(), nullable=True),
        sa.Column("isin", sa.String(length=12), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("data_file_id", sa.BigInteger(), nullable=False),
        sa.Column("loaded_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["data_file_id"],
            ["data_files.id"],
        ),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["instruments.id"],
        ),
        sa.PrimaryKeyConstraint("instrument_id", "session_date", "series"),
    )
    op.create_index(op.f("ix_eod_raw_data_file_id"), "eod_raw", ["data_file_id"], unique=False)
    op.create_index(op.f("ix_eod_raw_session_date"), "eod_raw", ["session_date"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_eod_raw_session_date"), table_name="eod_raw")
    op.drop_index(op.f("ix_eod_raw_data_file_id"), table_name="eod_raw")
    op.drop_table("eod_raw")
    op.drop_index(op.f("ix_eod_extras_session_date"), table_name="eod_extras")
    op.drop_index(op.f("ix_eod_extras_data_file_id"), table_name="eod_extras")
    op.drop_table("eod_extras")
    op.drop_index(op.f("ix_data_files_trading_date"), table_name="data_files")
    op.drop_index(op.f("ix_data_files_source"), table_name="data_files")
    op.drop_table("data_files")
