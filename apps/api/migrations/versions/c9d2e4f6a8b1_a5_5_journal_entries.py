"""A5.5 journal entries (M10.3): journal_entries, journal_entry_fills.

Revision ID: c9d2e4f6a8b1
Revises: e3a1c5d7f902
Create Date: 2026-11-26 23:30:00.000000

- ``journal_entries``: one row per round trip (flat to flat) in a book or a
  replay session: its home, instrument, ``entry_key`` (unique per user), the
  paired plan, status and times (copies the sync rewrites), and the user's
  text (review notes, mistakes, lessons, setup and mistake tags).
- ``journal_entry_fills``: each fill of an entry, a ``trades`` row or a
  ``replay_fills`` row (exactly one; each fill in at most one entry).

Additive; nothing is backfilled (the first read groups the fills). Figures are
never stored. The downgrade drops both tables, so it refuses while any entry
holds the user's text; entries without text are derived and safe to drop.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c9d2e4f6a8b1"
down_revision: str | None = "e3a1c5d7f902"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "journal_entries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("portfolio_id", sa.Integer(), nullable=True),
        sa.Column("replay_session_id", sa.Integer(), nullable=True),
        sa.Column("instrument_id", sa.BigInteger(), nullable=False),
        sa.Column("entry_key", sa.String(length=160), nullable=False),
        sa.Column("plan_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("opened_at", sa.DateTime(), nullable=False),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
        sa.Column("review_notes", sa.Text(), nullable=True),
        sa.Column("mistakes", sa.Text(), nullable=True),
        sa.Column("lessons", sa.Text(), nullable=True),
        sa.Column(
            "setup_tags",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'"),
            nullable=False,
        ),
        sa.Column(
            "mistake_tags",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "source IN ('paper', 'imported', 'replay')", name="ck_journal_entries_source"
        ),
        sa.CheckConstraint(
            "status IN ('open', 'closed', 'detached')", name="ck_journal_entries_status"
        ),
        sa.CheckConstraint(
            "(source = 'replay' AND replay_session_id IS NOT NULL AND portfolio_id IS NULL) "
            "OR (source IN ('paper', 'imported') AND portfolio_id IS NOT NULL "
            "AND replay_session_id IS NULL)",
            name="ck_journal_entries_home",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["portfolio_id"], ["portfolios.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["replay_session_id"], ["replay_sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["instrument_id"], ["instruments.id"]),
        sa.ForeignKeyConstraint(["plan_id"], ["trade_plans.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "entry_key", name="uq_journal_entries_user_key"),
    )
    for column in ("user_id", "portfolio_id", "replay_session_id", "instrument_id", "plan_id"):
        op.create_index(f"ix_journal_entries_{column}", "journal_entries", [column])
    op.create_index("ix_journal_entries_user_opened", "journal_entries", ["user_id", "opened_at"])

    op.create_table(
        "journal_entry_fills",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("entry_id", sa.Integer(), nullable=False),
        sa.Column("trade_id", sa.Integer(), nullable=True),
        sa.Column("replay_fill_id", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "(trade_id IS NULL) <> (replay_fill_id IS NULL)", name="ck_journal_entry_fills_one"
        ),
        sa.ForeignKeyConstraint(["entry_id"], ["journal_entries.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["trade_id"], ["trades.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["replay_fill_id"], ["replay_fills.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("trade_id", name="journal_entry_fills_trade_id_key"),
        sa.UniqueConstraint("replay_fill_id", name="journal_entry_fills_replay_fill_id_key"),
    )
    op.create_index("ix_journal_entry_fills_entry_id", "journal_entry_fills", ["entry_id"])


def downgrade() -> None:
    bind = op.get_bind()
    kept = bind.execute(
        sa.text(
            "SELECT count(*) FROM journal_entries WHERE "
            "coalesce(btrim(review_notes), '') <> '' OR coalesce(btrim(mistakes), '') <> '' "
            "OR coalesce(btrim(lessons), '') <> '' OR setup_tags <> '[]'::jsonb "
            "OR mistake_tags <> '[]'::jsonb"
        )
    ).scalar_one()
    if kept:
        raise RuntimeError(
            f"Refusing to downgrade: {kept} journal entr(y/ies) hold your notes or tags. "
            "Older code has nowhere to keep them; clear them first."
        )
    op.drop_index("ix_journal_entry_fills_entry_id", table_name="journal_entry_fills")
    op.drop_table("journal_entry_fills")
    op.drop_index("ix_journal_entries_user_opened", table_name="journal_entries")
    for column in ("user_id", "portfolio_id", "replay_session_id", "instrument_id", "plan_id"):
        op.drop_index(f"ix_journal_entries_{column}", table_name="journal_entries")
    op.drop_table("journal_entries")
