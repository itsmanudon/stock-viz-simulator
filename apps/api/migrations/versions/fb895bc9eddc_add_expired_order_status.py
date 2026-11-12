"""add expired order status

Revision ID: fb895bc9eddc
Revises: 80ee1abeca07
Create Date: 2026-11-12 01:03:04.726579

"""

from collections.abc import Sequence

from alembic import op


revision: str = "fb895bc9eddc"
down_revision: str | None = "80ee1abeca07"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Orders unfilled after 30 days expire (audit LG-6).

    ``pending_orders.status`` is the native ``orderstatus`` enum on
    PostgreSQL. ``ADD VALUE`` runs outside the migration transaction.
    SQLite stores the label as text and needs nothing.
    """
    if op.get_bind().dialect.name != "postgresql":
        return
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE orderstatus ADD VALUE IF NOT EXISTS 'EXPIRED'")


def downgrade() -> None:
    """PostgreSQL cannot drop an enum value; expired orders become cancelled.

    The ``EXPIRED`` label stays on the type, unused, which is harmless.
    """
    op.execute(
        "UPDATE pending_orders SET status = 'CANCELLED', "
        "cancel_reason = COALESCE(cancel_reason, 'Expired') WHERE status = 'EXPIRED'"
    )
