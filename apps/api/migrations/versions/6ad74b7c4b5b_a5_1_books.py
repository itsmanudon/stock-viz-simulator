"""A5.1 books (M10.1): many portfolios per user.

``portfolios`` loses its unique ``user_id`` index and gains ``kind``
(``paper`` | ``imported``), ``is_default``, ``cash_tracked``, ``broker``,
``holder_kind`` (``self`` | ``family`` | ``huf``), ``holder_label`` (no PAN)
and ``archived_at``. A partial unique index on ``(user_id) WHERE is_default``
keeps the race guard the old index gave: two concurrent first requests still
collide and the loser re-reads. ``(user_id, name)`` is unique.

Data: every existing portfolio becomes its user's default paper book with
cash tracked. Nothing moves. The updates are idempotent (they set the same
values on a rerun).

``portfolio_snapshots`` gains ``portfolio_id`` (backfilled from the user's
one book, NOT NULL) and is unique on ``(portfolio_id, date)``; ``user_id``
stays. The upgrade stops if a snapshot belongs to a user with no book (no
writer creates one; nothing is deleted silently).

``corporate_action_applications`` gains a nullable ``portfolio_id``: a row
with it is one book's rebase, unique on ``(action_id, portfolio_id)``; a
row without it is the user's alert rebase, unique on ``(action_id,
user_id) WHERE portfolio_id IS NULL``. Each existing row (it covered the
user's book and alerts) stays as the user row and gains a book row with the
same summary, so a rerun after the upgrade rebases nothing twice.

``alerts`` gains a nullable ``portfolio_id`` (cascade): the book a portfolio
rule watches; null means the default book.

**Downgrade rule.** The old schema holds one book per user. The downgrade
**refuses** (raises, nothing changed) while any user holds more than one
book, naming how many users do: delete or merge the extra books first.
Dropping them silently would lose the user's records. Otherwise it drops
the new columns, folds the book rows of ``corporate_action_applications``
back into one row per (action, user), and restores the unique indexes.

Revision ID: 6ad74b7c4b5b
Revises: 53b66a2e2ec2
Create Date: 2026-11-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "6ad74b7c4b5b"
down_revision: str | None = "53b66a2e2ec2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- portfolios ------------------------------------------------------
    op.add_column(
        "portfolios",
        sa.Column("kind", sa.String(length=16), server_default="paper", nullable=False),
    )
    op.add_column(
        "portfolios",
        sa.Column("is_default", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column(
        "portfolios",
        sa.Column("cash_tracked", sa.Boolean(), server_default=sa.text("true"), nullable=False),
    )
    op.add_column("portfolios", sa.Column("broker", sa.String(length=16), nullable=True))
    op.add_column(
        "portfolios",
        sa.Column("holder_kind", sa.String(length=8), server_default="self", nullable=False),
    )
    op.add_column("portfolios", sa.Column("holder_label", sa.String(length=60), nullable=True))
    op.add_column("portfolios", sa.Column("archived_at", sa.DateTime(), nullable=True))

    # Existing books: each user's one portfolio is their default paper book.
    op.execute(
        "UPDATE portfolios SET kind = 'paper', is_default = true, cash_tracked = true, "
        "archived_at = NULL"
    )

    op.drop_index("ix_portfolios_user_id", table_name="portfolios")
    op.create_index("ix_portfolios_user_id", "portfolios", ["user_id"], unique=False)
    op.create_index(
        "uq_portfolios_user_default",
        "portfolios",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("is_default"),
    )
    op.create_unique_constraint("uq_portfolios_user_name", "portfolios", ["user_id", "name"])
    op.create_check_constraint("ck_portfolios_kind", "portfolios", "kind IN ('paper', 'imported')")
    op.create_check_constraint(
        "ck_portfolios_holder_kind", "portfolios", "holder_kind IN ('self', 'family', 'huf')"
    )
    op.create_check_constraint(
        "ck_portfolios_broker", "portfolios", "broker IS NULL OR broker IN ('zerodha')"
    )
    op.create_check_constraint(
        "ck_portfolios_default_not_archived",
        "portfolios",
        "NOT (is_default AND archived_at IS NOT NULL)",
    )

    # --- portfolio_snapshots ---------------------------------------------
    conn = op.get_bind()
    orphans = conn.execute(
        sa.text(
            "SELECT count(*) FROM portfolio_snapshots s WHERE NOT EXISTS "
            "(SELECT 1 FROM portfolios p WHERE p.user_id = s.user_id)"
        )
    ).scalar_one()
    if orphans:
        raise RuntimeError(
            f"A5.1: {orphans} portfolio_snapshots row(s) belong to users with no portfolio, so "
            "they can't be keyed to a book. Inspect them; nothing was changed."
        )
    op.add_column("portfolio_snapshots", sa.Column("portfolio_id", sa.Integer(), nullable=True))
    op.execute(
        "UPDATE portfolio_snapshots s SET portfolio_id = p.id FROM portfolios p "
        "WHERE p.user_id = s.user_id AND s.portfolio_id IS NULL"
    )
    op.alter_column("portfolio_snapshots", "portfolio_id", nullable=False)
    op.create_foreign_key(
        "portfolio_snapshots_portfolio_id_fkey",
        "portfolio_snapshots",
        "portfolios",
        ["portfolio_id"],
        ["id"],
    )
    op.create_index("ix_portfolio_snapshots_portfolio_id", "portfolio_snapshots", ["portfolio_id"])
    op.drop_constraint("uq_portfolio_snapshots_user_date", "portfolio_snapshots", type_="unique")
    op.create_unique_constraint(
        "uq_portfolio_snapshots_portfolio_date", "portfolio_snapshots", ["portfolio_id", "date"]
    )

    # --- corporate_action_applications -----------------------------------
    op.add_column(
        "corporate_action_applications", sa.Column("portfolio_id", sa.Integer(), nullable=True)
    )
    op.create_foreign_key(
        "corporate_action_applications_portfolio_id_fkey",
        "corporate_action_applications",
        "portfolios",
        ["portfolio_id"],
        ["id"],
    )
    op.create_index(
        "ix_corporate_action_applications_portfolio_id",
        "corporate_action_applications",
        ["portfolio_id"],
    )
    op.drop_constraint(
        "uq_corporate_action_applications", "corporate_action_applications", type_="unique"
    )
    # Each old row covered the user's book and alerts: keep it as the user
    # row and add the book row beside it.
    op.execute(
        "INSERT INTO corporate_action_applications "
        "(action_id, user_id, portfolio_id, applied_at, summary) "
        "SELECT a.action_id, a.user_id, p.id, a.applied_at, a.summary "
        "FROM corporate_action_applications a JOIN portfolios p ON p.user_id = a.user_id "
        "WHERE a.portfolio_id IS NULL AND NOT EXISTS ("
        "SELECT 1 FROM corporate_action_applications b "
        "WHERE b.action_id = a.action_id AND b.portfolio_id = p.id)"
    )
    op.create_unique_constraint(
        "uq_corporate_action_applications_book",
        "corporate_action_applications",
        ["action_id", "portfolio_id"],
    )
    op.create_index(
        "uq_corporate_action_applications_user",
        "corporate_action_applications",
        ["action_id", "user_id"],
        unique=True,
        postgresql_where=sa.text("portfolio_id IS NULL"),
    )

    # --- alerts ----------------------------------------------------------
    op.add_column("alerts", sa.Column("portfolio_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_alerts_portfolio_id",
        "alerts",
        "portfolios",
        ["portfolio_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_alerts_portfolio_id", "alerts", ["portfolio_id"])


def downgrade() -> None:
    conn = op.get_bind()
    many = conn.execute(
        sa.text(
            "SELECT count(*) FROM (SELECT user_id FROM portfolios GROUP BY user_id "
            "HAVING count(*) > 1) m"
        )
    ).scalar_one()
    if many:
        raise RuntimeError(
            f"A5.1 downgrade refused: {many} user(s) hold more than one book, and the old "
            "schema allows one. Delete or merge the extra books first; nothing was changed."
        )

    # --- alerts ----------------------------------------------------------
    op.drop_index("ix_alerts_portfolio_id", table_name="alerts")
    op.drop_constraint("fk_alerts_portfolio_id", "alerts", type_="foreignkey")
    op.drop_column("alerts", "portfolio_id")

    # --- corporate_action_applications -----------------------------------
    op.drop_index(
        "uq_corporate_action_applications_user", table_name="corporate_action_applications"
    )
    op.drop_constraint(
        "uq_corporate_action_applications_book", "corporate_action_applications", type_="unique"
    )
    # One row per (action, user): drop a book row whose user row exists,
    # then turn the rest into user rows.
    op.execute(
        "DELETE FROM corporate_action_applications b WHERE b.portfolio_id IS NOT NULL "
        "AND EXISTS (SELECT 1 FROM corporate_action_applications u WHERE "
        "u.action_id = b.action_id AND u.user_id = b.user_id AND u.portfolio_id IS NULL)"
    )
    op.execute("UPDATE corporate_action_applications SET portfolio_id = NULL")
    op.drop_index(
        "ix_corporate_action_applications_portfolio_id",
        table_name="corporate_action_applications",
    )
    op.drop_constraint(
        "corporate_action_applications_portfolio_id_fkey",
        "corporate_action_applications",
        type_="foreignkey",
    )
    op.drop_column("corporate_action_applications", "portfolio_id")
    op.create_unique_constraint(
        "uq_corporate_action_applications",
        "corporate_action_applications",
        ["action_id", "user_id"],
    )

    # --- portfolio_snapshots ---------------------------------------------
    op.drop_constraint(
        "uq_portfolio_snapshots_portfolio_date", "portfolio_snapshots", type_="unique"
    )
    op.drop_index("ix_portfolio_snapshots_portfolio_id", table_name="portfolio_snapshots")
    op.drop_constraint(
        "portfolio_snapshots_portfolio_id_fkey", "portfolio_snapshots", type_="foreignkey"
    )
    op.drop_column("portfolio_snapshots", "portfolio_id")
    op.create_unique_constraint(
        "uq_portfolio_snapshots_user_date", "portfolio_snapshots", ["user_id", "date"]
    )

    # --- portfolios ------------------------------------------------------
    for name in (
        "ck_portfolios_default_not_archived",
        "ck_portfolios_broker",
        "ck_portfolios_holder_kind",
        "ck_portfolios_kind",
    ):
        op.drop_constraint(name, "portfolios", type_="check")
    op.drop_constraint("uq_portfolios_user_name", "portfolios", type_="unique")
    op.drop_index("uq_portfolios_user_default", table_name="portfolios")
    op.drop_index("ix_portfolios_user_id", table_name="portfolios")
    op.create_index("ix_portfolios_user_id", "portfolios", ["user_id"], unique=True)
    for column in (
        "archived_at",
        "holder_label",
        "holder_kind",
        "broker",
        "cash_tracked",
        "is_default",
        "kind",
    ):
        op.drop_column("portfolios", column)
