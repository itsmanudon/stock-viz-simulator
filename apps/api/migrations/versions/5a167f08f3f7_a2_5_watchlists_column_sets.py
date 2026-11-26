"""many watchlists, item notes and tags, column sets (A2.5)

Revision ID: 5a167f08f3f7
Revises: 65fc5117cbf1
Create Date: 2026-11-26 12:00:00.000000

Additive (M4.6). ``watchlists`` gains ``colour`` (default ``aqua``),
``position``, ``is_default`` and ``column_set_id``; ``watchlist_items`` gains
``note`` (up to 2,000 characters) and ``tags`` (JSON list, default ``[]``);
``column_sets`` is new.

Existing rows are kept. Before the unique keys land, each user's lists are
numbered by id (``position``), the oldest becomes the default (it is the list
the old single-list code read), and a repeated name gets " (2)", " (3)" ...
so ``uq_watchlists_user_name`` holds. ``uq_watchlists_user_default`` is a
partial unique index: one default per user.

The downgrade drops the new columns, keys and table. Lists beyond the first
stay as rows; older code reads the first by id, which is the default list
for every user whose default never moved.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "5a167f08f3f7"
down_revision: str | None = "65fc5117cbf1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "column_sets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("columns", JSON, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "name", name="uq_column_sets_user_name"),
    )
    op.create_index("ix_column_sets_user_id", "column_sets", ["user_id"], unique=False)

    op.add_column("watchlist_items", sa.Column("note", sa.String(length=2000), nullable=True))
    op.add_column(
        "watchlist_items",
        sa.Column("tags", JSON, nullable=False, server_default=sa.text("'[]'")),
    )
    op.add_column(
        "watchlists",
        sa.Column("colour", sa.String(length=16), nullable=False, server_default="aqua"),
    )
    op.add_column(
        "watchlists",
        sa.Column("position", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "watchlists",
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("watchlists", sa.Column("column_set_id", sa.Integer(), nullable=True))

    # Number each user's lists, flag the oldest, and make names unique.
    op.execute(
        """
        WITH ranked AS (
            SELECT id,
                   row_number() OVER (PARTITION BY user_id ORDER BY id) - 1 AS pos,
                   row_number() OVER (PARTITION BY user_id, name ORDER BY id) AS dup
            FROM watchlists
        )
        UPDATE watchlists w
        SET position = ranked.pos,
            is_default = (ranked.pos = 0),
            name = CASE WHEN ranked.dup > 1
                        THEN left(w.name, 120) || ' (' || ranked.dup || ')'
                        ELSE w.name END
        FROM ranked
        WHERE w.id = ranked.id
        """
    )

    op.create_index(
        "uq_watchlists_user_default",
        "watchlists",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("is_default"),
    )
    op.create_unique_constraint("uq_watchlists_user_name", "watchlists", ["user_id", "name"])
    op.create_foreign_key(
        "fk_watchlists_column_set_id",
        "watchlists",
        "column_sets",
        ["column_set_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_watchlists_column_set_id", "watchlists", type_="foreignkey")
    op.drop_constraint("uq_watchlists_user_name", "watchlists", type_="unique")
    op.drop_index("uq_watchlists_user_default", table_name="watchlists")
    op.drop_column("watchlists", "column_set_id")
    op.drop_column("watchlists", "is_default")
    op.drop_column("watchlists", "position")
    op.drop_column("watchlists", "colour")
    op.drop_column("watchlist_items", "tags")
    op.drop_column("watchlist_items", "note")
    op.drop_index("ix_column_sets_user_id", table_name="column_sets")
    op.drop_table("column_sets")
