"""A5.3 broker imports (M10.2 CSV part): import_batches, broker_fills, trades.broker_fill_id.

Revision ID: e3a1c5d7f902
Revises: b5d4a7e1c902
Create Date: 2026-11-26 21:00:00.000000

- ``import_batches``: one row per committed upload into an imported book: the
  column map, the file's SHA-256 and row counts. No file body, file name or
  client id.
- ``broker_fills``: one row per broker trade (or opening lot) as traded,
  unique on ``(portfolio_id, broker, exchange, trade_id)`` (the dedupe key).
- ``trades.broker_fill_id`` (nullable, unique, cascade): the fill a trade of
  an imported book posts.

Additive. The downgrade drops the three (an imported book's posted trades go
with their fills), so it refuses while any broker fill exists.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e3a1c5d7f902"
down_revision: str | None = "b5d4a7e1c902"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "import_batches",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("portfolio_id", sa.Integer(), nullable=False),
        sa.Column("broker", sa.String(length=16), nullable=False),
        sa.Column("column_map", sa.String(length=40), nullable=False),
        sa.Column("file_sha256", sa.String(length=64), nullable=False),
        sa.Column("rows_total", sa.Integer(), nullable=False),
        sa.Column("rows_added", sa.Integer(), nullable=False),
        sa.Column("rows_duplicate", sa.Integer(), nullable=False),
        sa.Column("rows_unmatched", sa.Integer(), nullable=False),
        sa.Column("rows_skipped_segment", sa.Integer(), nullable=False),
        sa.Column("rows_rejected", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("broker IN ('zerodha')", name="ck_import_batches_broker"),
        sa.ForeignKeyConstraint(["portfolio_id"], ["portfolios.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_import_batches_portfolio_id", "import_batches", ["portfolio_id"])
    op.create_index(
        "ix_import_batches_portfolio_created", "import_batches", ["portfolio_id", "created_at"]
    )

    op.create_table(
        "broker_fills",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("portfolio_id", sa.Integer(), nullable=False),
        sa.Column("import_batch_id", sa.Integer(), nullable=True),
        sa.Column("kind", sa.String(length=8), nullable=False),
        sa.Column("broker", sa.String(length=16), nullable=False),
        sa.Column("exchange", sa.String(length=8), nullable=False),
        sa.Column("segment", sa.String(length=16), nullable=True),
        sa.Column("series", sa.String(length=8), nullable=True),
        sa.Column("trade_id", sa.String(length=40), nullable=True),
        sa.Column("order_id", sa.String(length=40), nullable=True),
        sa.Column("instrument_id", sa.BigInteger(), nullable=False),
        sa.Column("ticker", sa.String(length=16), nullable=False),
        sa.Column("isin", sa.String(length=12), nullable=True),
        sa.Column("raw_symbol", sa.String(length=40), nullable=True),
        sa.Column("side", sa.String(length=4), nullable=False),
        sa.Column("quantity", sa.Numeric(20, 6), nullable=False),
        sa.Column("price", sa.Numeric(18, 6), nullable=False),
        sa.Column("executed_at", sa.DateTime(), nullable=False),
        sa.Column("time_known", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("auction", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="posted", nullable=False),
        sa.Column("product", sa.String(length=10), nullable=True),
        sa.Column("fees", sa.Numeric(20, 6), nullable=True),
        sa.Column("fee_source", sa.String(length=12), nullable=True),
        sa.Column("fee_lines", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("basis_uncertain", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("kind IN ('trade', 'opening')", name="ck_broker_fills_kind"),
        sa.CheckConstraint("side IN ('buy', 'sell')", name="ck_broker_fills_side"),
        sa.CheckConstraint("quantity > 0 AND price > 0", name="ck_broker_fills_quantity_price"),
        sa.CheckConstraint(
            "status IN ('posted', 'needs_opening_lot')", name="ck_broker_fills_status"
        ),
        sa.CheckConstraint(
            "(kind = 'opening') = (import_batch_id IS NULL)", name="ck_broker_fills_batch"
        ),
        sa.ForeignKeyConstraint(["portfolio_id"], ["portfolios.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["import_batch_id"], ["import_batches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["instrument_id"], ["instruments.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "portfolio_id", "broker", "exchange", "trade_id", name="uq_broker_fills_trade"
        ),
    )
    op.create_index("ix_broker_fills_portfolio_id", "broker_fills", ["portfolio_id"])
    op.create_index("ix_broker_fills_import_batch_id", "broker_fills", ["import_batch_id"])
    op.create_index("ix_broker_fills_instrument_id", "broker_fills", ["instrument_id"])
    op.create_index(
        "ix_broker_fills_portfolio_executed", "broker_fills", ["portfolio_id", "executed_at"]
    )

    op.add_column("trades", sa.Column("broker_fill_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "trades_broker_fill_id_fkey",
        "trades",
        "broker_fills",
        ["broker_fill_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_unique_constraint("trades_broker_fill_id_key", "trades", ["broker_fill_id"])


def downgrade() -> None:
    bind = op.get_bind()
    kept = bind.execute(sa.text("SELECT count(*) FROM broker_fills")).scalar_one()
    if kept:
        raise RuntimeError(
            f"Refusing to downgrade: {kept} broker fill(s) exist. Older code has nowhere to "
            "keep imported trades; delete the imports (or the imported books) first."
        )
    op.drop_constraint("trades_broker_fill_id_key", "trades", type_="unique")
    op.drop_constraint("trades_broker_fill_id_fkey", "trades", type_="foreignkey")
    op.drop_column("trades", "broker_fill_id")
    op.drop_index("ix_broker_fills_portfolio_executed", table_name="broker_fills")
    op.drop_index("ix_broker_fills_instrument_id", table_name="broker_fills")
    op.drop_index("ix_broker_fills_import_batch_id", table_name="broker_fills")
    op.drop_index("ix_broker_fills_portfolio_id", table_name="broker_fills")
    op.drop_table("broker_fills")
    op.drop_index("ix_import_batches_portfolio_created", table_name="import_batches")
    op.drop_index("ix_import_batches_portfolio_id", table_name="import_batches")
    op.drop_table("import_batches")
