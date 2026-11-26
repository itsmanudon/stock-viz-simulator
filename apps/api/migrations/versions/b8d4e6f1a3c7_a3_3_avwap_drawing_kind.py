"""A3.3 (M2.5): the ``avwap`` drawing kind.

Additive: ``ck_drawings_kind`` gains ``avwap`` (an anchored VWAP: one point,
its anchor date, with a null price). The downgrade deletes ``avwap`` rows,
which older code cannot read, then restores the A3.2 constraint.

Revision ID: b8d4e6f1a3c7
Revises: f3bb96a753c6
Create Date: 2026-11-26 12:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

revision: str = "b8d4e6f1a3c7"
down_revision: str | None = "f3bb96a753c6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_A3_2 = (
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
)


def _check(kinds: tuple[str, ...]) -> str:
    return "kind IN (" + ", ".join(f"'{k}'" for k in kinds) + ")"


def upgrade() -> None:
    with op.batch_alter_table("drawings") as batch:
        batch.drop_constraint("ck_drawings_kind", type_="check")
        batch.create_check_constraint("ck_drawings_kind", _check((*_A3_2, "avwap")))


def downgrade() -> None:
    op.execute("DELETE FROM drawings WHERE kind = 'avwap'")
    with op.batch_alter_table("drawings") as batch:
        batch.drop_constraint("ck_drawings_kind", type_="check")
        batch.create_check_constraint("ck_drawings_kind", _check(_A3_2))
