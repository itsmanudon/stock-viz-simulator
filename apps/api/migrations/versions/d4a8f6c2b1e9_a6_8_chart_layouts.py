"""A6.8 chart layouts: ``chart_templates`` and ``chart_layouts``.

Revision ID: d4a8f6c2b1e9
Revises: c8d3e5f7a9b2
Create Date: 2026-11-27 18:00:00.000000

- ``chart_templates``: a saved chart look per user (chart type, scale,
  indicator keys, pane heights by pane kind), named uniquely per user.
- ``chart_layouts``: a saved chart workspace per user (grid ``1``, ``2v``,
  ``2h`` or ``4``, and its panes as JSON: symbol, interval, template id,
  link colour), named uniquely per user.

Additive. The downgrade drops both tables.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d4a8f6c2b1e9"
down_revision: str | None = "c8d3e5f7a9b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")

CHART_TYPES = "chart_type IN ('candles', 'hollow', 'bars', 'line', 'area', 'heikin-ashi')"
SCALES = "scale IN ('linear', 'log', 'percent')"
GRIDS = "grid IN ('1', '2v', '2h', '4')"


def upgrade() -> None:
    op.create_table(
        "chart_templates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("chart_type", sa.String(length=16), nullable=False),
        sa.Column("scale", sa.String(length=16), nullable=False),
        sa.Column("indicators", JSON, nullable=False),
        sa.Column("pane_heights", JSON, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(CHART_TYPES, name="ck_chart_templates_chart_type"),
        sa.CheckConstraint(SCALES, name="ck_chart_templates_scale"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "name", name="uq_chart_templates_user_name"),
    )
    op.create_index("ix_chart_templates_user_id", "chart_templates", ["user_id"], unique=False)
    op.create_table(
        "chart_layouts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("grid", sa.String(length=4), nullable=False),
        sa.Column("panes", JSON, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(GRIDS, name="ck_chart_layouts_grid"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "name", name="uq_chart_layouts_user_name"),
    )
    op.create_index("ix_chart_layouts_user_id", "chart_layouts", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_chart_layouts_user_id", table_name="chart_layouts")
    op.drop_table("chart_layouts")
    op.drop_index("ix_chart_templates_user_id", table_name="chart_templates")
    op.drop_table("chart_templates")
