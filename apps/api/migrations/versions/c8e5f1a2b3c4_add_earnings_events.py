"""add earnings events

Revision ID: c8e5f1a2b3c4
Revises: c5f9d3e2b016
Create Date: 2026-08-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "c8e5f1a2b3c4"
down_revision: str | None = "c5f9d3e2b016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "earnings_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ticker", sqlmodel.sql.sqltypes.AutoString(length=16), nullable=False),
        sa.Column("event_date", sa.Date(), nullable=False),
        sa.Column("report_time", sqlmodel.sql.sqltypes.AutoString(length=32), nullable=True),
        sa.Column("fiscal_period", sqlmodel.sql.sqltypes.AutoString(length=32), nullable=False),
        sa.Column("eps_estimate", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column("eps_actual", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column("surprise_pct", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column("source", sqlmodel.sql.sqltypes.AutoString(length=32), nullable=False),
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["ticker"], ["symbols.ticker"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "ticker", "event_date", "fiscal_period", name="uq_earnings_events_identity"
        ),
    )
    op.create_index("ix_earnings_events_date_ticker", "earnings_events", ["event_date", "ticker"])
    op.create_index(op.f("ix_earnings_events_event_date"), "earnings_events", ["event_date"])
    op.create_index(op.f("ix_earnings_events_ticker"), "earnings_events", ["ticker"])


def downgrade() -> None:
    op.drop_index(op.f("ix_earnings_events_ticker"), table_name="earnings_events")
    op.drop_index(op.f("ix_earnings_events_event_date"), table_name="earnings_events")
    op.drop_index("ix_earnings_events_date_ticker", table_name="earnings_events")
    op.drop_table("earnings_events")
