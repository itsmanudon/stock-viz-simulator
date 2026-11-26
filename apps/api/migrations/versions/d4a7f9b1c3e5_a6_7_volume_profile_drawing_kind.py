"""A6.7 (M2.9): the ``volume_profile`` drawing kind.

Additive: ``ck_drawings_kind`` gains ``volume_profile`` (a fixed-range volume
profile: two points, its first and last session, with null prices). The
downgrade refuses while a ``volume_profile`` drawing is stored (older code
cannot read one); delete them first.

Revision ID: d4a7f9b1c3e5
Revises: d4a8f6c2b1e9
Create Date: 2026-11-26 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d4a7f9b1c3e5"
down_revision: str | None = "d4a8f6c2b1e9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_A3_3 = (
    "trendline",
    "ray",
    "hline",
    "rectangle",
    "channel",
    "fib_retracement",
    "fib_extension",
    "ruler",
    "text",
    "position_long",
    "position_short",
    "avwap",
)


def _check(kinds: tuple[str, ...]) -> str:
    return "kind IN (" + ", ".join(f"'{k}'" for k in kinds) + ")"


def upgrade() -> None:
    with op.batch_alter_table("drawings") as batch:
        batch.drop_constraint("ck_drawings_kind", type_="check")
        batch.create_check_constraint("ck_drawings_kind", _check((*_A3_3, "volume_profile")))


def downgrade() -> None:
    stored = (
        op.get_bind()
        .execute(sa.text("SELECT count(*) FROM drawings WHERE kind = 'volume_profile'"))
        .scalar_one()
    )
    if stored:
        raise RuntimeError(
            f"{stored} volume_profile drawings are stored; delete them before downgrading"
        )
    with op.batch_alter_table("drawings") as batch:
        batch.drop_constraint("ck_drawings_kind", type_="check")
        batch.create_check_constraint("ck_drawings_kind", _check(_A3_3))
