"""A6.11 broker maps: more import brokers and saved column maps.

Revision ID: d1a6b11c2e40
Revises: d4a7f9b1c3e5
Create Date: 2026-11-26 18:00:00.000000

- ``portfolios.broker`` and ``import_batches.broker`` may also be ``dhan``,
  ``fyers``, ``upstox``, ``angelone``, ``groww`` or ``other`` (a book read with
  the user's own column map, a US broker for example).
- ``import_column_maps``: "Map columns yourself", saved per user: a name,
  field -> header names (never a cell value), a default exchange for Indian
  rows without one, and the date order.

Additive. The downgrade refuses while a book or batch names a new broker.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d1a6b11c2e40"
down_revision: str | None = "d4a7f9b1c3e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW = "'zerodha', 'dhan', 'fyers', 'upstox', 'angelone', 'groww', 'other'"
OLD = "'zerodha'"


def _brokers(values: str) -> None:
    op.drop_constraint("ck_portfolios_broker", "portfolios", type_="check")
    op.create_check_constraint(
        "ck_portfolios_broker", "portfolios", f"broker IS NULL OR broker IN ({values})"
    )
    op.drop_constraint("ck_import_batches_broker", "import_batches", type_="check")
    op.create_check_constraint(
        "ck_import_batches_broker", "import_batches", f"broker IN ({values})"
    )


def upgrade() -> None:
    _brokers(NEW)
    op.create_table(
        "import_column_maps",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=60), nullable=False),
        sa.Column(
            "mapping",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("default_exchange", sa.String(length=3), nullable=True),
        sa.Column("date_order", sa.String(length=12), nullable=False, server_default="auto"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("user_id", "name", name="uq_import_column_maps_user_name"),
        sa.CheckConstraint(
            "default_exchange IS NULL OR default_exchange IN ('NSE', 'BSE')",
            name="ck_import_column_maps_exchange",
        ),
        sa.CheckConstraint(
            "date_order IN ('auto', 'day_first', 'month_first')",
            name="ck_import_column_maps_date_order",
        ),
    )
    op.create_index("ix_import_column_maps_user_id", "import_column_maps", ["user_id"])


def downgrade() -> None:
    bind = op.get_bind()
    used = bind.execute(
        sa.text(
            "SELECT (SELECT count(*) FROM portfolios WHERE broker IS NOT NULL "
            "AND broker <> 'zerodha') + (SELECT count(*) FROM import_batches "
            "WHERE broker <> 'zerodha')"
        )
    ).scalar_one()
    if used:
        raise RuntimeError(
            "books or imports name a broker other than zerodha; delete them before downgrading"
        )
    op.drop_index("ix_import_column_maps_user_id", table_name="import_column_maps")
    op.drop_table("import_column_maps")
    _brokers(OLD)
