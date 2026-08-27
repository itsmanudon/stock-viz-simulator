"""add simulated_executions provenance table

Additive 1:1 provenance for live equity paper fills (SIM-04). Existing
``trades`` rows are left without provenance; there is no backfill.

Revision ID: b4e8c2d1a905
Revises: a8c3e1f4b902
Create Date: 2026-08-27
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b4e8c2d1a905"
down_revision: str | None = "a8c3e1f4b902"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "simulated_executions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("trade_id", sa.Integer(), nullable=False),
        sa.Column("profile_name", sa.String(length=64), nullable=False),
        sa.Column("model_version", sa.String(length=32), nullable=False),
        sa.Column("reference_price", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column("fill_price", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "assumptions",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("market_interval", sa.String(length=16), nullable=False),
        sa.Column("order_type", sa.String(length=16), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["trade_id"], ["trades.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("trade_id", name="uq_simulated_executions_trade_id"),
    )


def downgrade() -> None:
    op.drop_table("simulated_executions")
