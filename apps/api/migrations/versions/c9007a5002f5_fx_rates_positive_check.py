"""fx rates positive check

Revision ID: c9007a5002f5
Revises: 995a6a786e10
Create Date: 2026-11-12 14:37:18.404696

"""

from collections.abc import Sequence

from alembic import op


revision: str = "c9007a5002f5"
down_revision: str | None = "995a6a786e10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Audit MD-7: refuse a NaN, zero or negative FX rate. Production held none
    (read-only check, 12 Nov 2026), so the constraint applies to existing rows."""
    op.create_check_constraint(
        "ck_fx_rates_usd_rate_positive", "fx_rates", "usd_rate > 0 AND usd_rate <> 'NaN'"
    )


def downgrade() -> None:
    op.drop_constraint("ck_fx_rates_usd_rate_positive", "fx_rates", type_="check")
