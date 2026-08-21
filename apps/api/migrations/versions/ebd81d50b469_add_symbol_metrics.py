"""add symbol_metrics

Precomputed per-symbol RSI / 52-week range / rolling sentiment, refreshed daily
by the scheduler. The screener reads these instead of rescanning ~260 bars per
symbol on every request.

Revision ID: ebd81d50b469
Revises: f3c9e7a24b81
Create Date: 2026-08-21 05:40:39.344285

"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op


revision: str = "ebd81d50b469"
down_revision: str | None = "f3c9e7a24b81"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "symbol_metrics",
        sa.Column("ticker", sqlmodel.sql.sqltypes.AutoString(length=16), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=True),
        sa.Column("last_close", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column("rsi_14", sa.Float(), nullable=True),
        sa.Column("high_52w", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column("low_52w", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column("sentiment_7d", sa.Float(), nullable=True),
        sa.Column("sentiment_article_count", sa.Integer(), nullable=False),
        sa.Column("computed_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["ticker"],
            ["symbols.ticker"],
        ),
        sa.PrimaryKeyConstraint("ticker"),
    )
    op.create_index(op.f("ix_symbol_metrics_as_of"), "symbol_metrics", ["as_of"], unique=False)
    op.create_index(op.f("ix_symbol_metrics_rsi_14"), "symbol_metrics", ["rsi_14"], unique=False)
    op.create_index(
        op.f("ix_symbol_metrics_sentiment_7d"), "symbol_metrics", ["sentiment_7d"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_symbol_metrics_sentiment_7d"), table_name="symbol_metrics")
    op.drop_index(op.f("ix_symbol_metrics_rsi_14"), table_name="symbol_metrics")
    op.drop_index(op.f("ix_symbol_metrics_as_of"), table_name="symbol_metrics")
    op.drop_table("symbol_metrics")
