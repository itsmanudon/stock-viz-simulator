"""align enum-typed columns with the models (VARCHAR -> native enum)

The baseline created ``trades.side`` as a native ``tradeside`` enum, but every
later migration wrote its enum-ish columns as ``VARCHAR``. The models declare
Python enums throughout, so SQLModel infers ``sa.Enum`` for all of them and
``alembic check`` reported six columns of drift. Nothing was broken at
runtime — SQLAlchemy writes the enum *name* either way, so the stored values
("BUY", "PENDING", ...) already match the enum labels — but the drift meant a
CI drift-check could never pass.

This converts the VARCHAR columns to the native enum types the models
describe. The ``USING col::text::enumtype`` cast is safe because the existing
values are exactly the enum labels.

Revision ID: f3c9e7a24b81
Revises: e2a8b4d15c73
Create Date: 2026-08-21
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f3c9e7a24b81"
down_revision: str | None = "e2a8b4d15c73"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (table, column, enum type name, labels, varchar length for downgrade)
_CONVERSIONS = [
    ("alerts", "direction", "alertdirection", ["ABOVE", "BELOW"], 8),
    ("options_positions", "option_type", "optiontype", ["CALL", "PUT"], 4),
    (
        "options_positions",
        "status",
        "optionstatus",
        ["OPEN", "CLOSED", "EXERCISED", "EXPIRED"],
        12,
    ),
    ("pending_orders", "side", "tradeside", ["BUY", "SELL"], 8),
    ("pending_orders", "order_type", "ordertype", ["LIMIT", "STOP_LOSS", "TAKE_PROFIT"], 16),
    ("pending_orders", "status", "orderstatus", ["PENDING", "FILLED", "CANCELLED"], 16),
]


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    # pending_orders.status carries a server default; drop it across the type
    # change and restore it afterwards.
    op.execute("ALTER TABLE pending_orders ALTER COLUMN status DROP DEFAULT")

    created: set[str] = set()
    for table, column, type_name, labels, _ in _CONVERSIONS:
        if type_name not in created:
            sa.Enum(*labels, name=type_name).create(bind, checkfirst=True)
            created.add(type_name)
        op.execute(
            f"ALTER TABLE {table} ALTER COLUMN {column} "
            f"TYPE {type_name} USING {column}::text::{type_name}"
        )

    op.execute("ALTER TABLE pending_orders ALTER COLUMN status SET DEFAULT 'PENDING'")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute("ALTER TABLE pending_orders ALTER COLUMN status DROP DEFAULT")
    for table, column, _type_name, _labels, length in _CONVERSIONS:
        op.execute(
            f"ALTER TABLE {table} ALTER COLUMN {column} TYPE VARCHAR({length}) USING {column}::text"
        )
    op.execute("ALTER TABLE pending_orders ALTER COLUMN status SET DEFAULT 'PENDING'")

    for type_name in ("alertdirection", "optiontype", "optionstatus", "ordertype", "orderstatus"):
        sa.Enum(name=type_name).drop(bind, checkfirst=True)
