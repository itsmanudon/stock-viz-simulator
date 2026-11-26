"""A4.7 drills and decks (M9.3): drill_decks, drills, drill_plans.

Additive. A deck is K replay sessions seeded from a rule's real triggers;
each drill links one replay session (cascade) and its plan keys on that
session, so A5's journal can absorb it. The downgrade drops the three
tables (their replay sessions stay).

Revision ID: 53b66a2e2ec2
Revises: a6c4e2f8b913
Create Date: 2026-11-26 07:19:01.182902

"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "53b66a2e2ec2"
down_revision: str | None = "a6c4e2f8b913"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "drill_plans",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("side", sa.String(length=8), server_default="long", nullable=False),
        sa.Column("planned_entry", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("planned_stop", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("planned_size", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("locked_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("side IN ('long')", name="ck_drill_plans_side"),
        sa.CheckConstraint(
            "planned_entry > 0 AND planned_stop > 0 AND planned_size > 0",
            name="ck_drill_plans_positive",
        ),
        sa.ForeignKeyConstraint(["session_id"], ["replay_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_drill_plans_session_id"), "drill_plans", ["session_id"], unique=True)
    op.create_table(
        "drill_decks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(length=120), nullable=False),
        sa.Column("setup_version_id", sa.Integer(), nullable=False),
        sa.Column("rule_text", sa.Text(), nullable=False),
        sa.Column("rule_hash", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False),
        sa.Column(
            "universe",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("from_date", sa.Date(), nullable=False),
        sa.Column("to_date", sa.Date(), nullable=False),
        sa.Column("k", sa.Integer(), nullable=False),
        sa.Column("lead_bars", sa.Integer(), nullable=False),
        sa.Column("follow_bars", sa.Integer(), nullable=False),
        sa.Column("seed", sa.BigInteger(), nullable=False),
        sa.Column("anonymised", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("triggers_found", sa.Integer(), nullable=False),
        sa.Column("triggers_eligible", sa.Integer(), nullable=False),
        sa.Column("lag_skipped", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("k BETWEEN 1 AND 25", name="ck_drill_decks_k"),
        sa.CheckConstraint("lead_bars >= 1 AND follow_bars >= 1", name="ck_drill_decks_bars"),
        sa.ForeignKeyConstraint(
            ["setup_version_id"],
            ["setup_versions.id"],
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_drill_decks_setup_version_id"), "drill_decks", ["setup_version_id"], unique=False
    )
    op.create_index(op.f("ix_drill_decks_user_id"), "drill_decks", ["user_id"], unique=False)
    op.create_table(
        "drills",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("deck_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("ticker", sqlmodel.sql.sqltypes.AutoString(length=16), nullable=False),
        sa.Column("trigger_at", sa.DateTime(), nullable=False),
        sa.Column("trigger_date", sa.Date(), nullable=False),
        sa.Column("date_offset_weeks", sa.Integer(), nullable=False),
        sa.Column("revealed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["deck_id"], ["drill_decks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["replay_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("deck_id", "position", name="uq_drills_deck_position"),
        sa.UniqueConstraint("session_id", name="uq_drills_session"),
    )
    op.create_index(op.f("ix_drills_deck_id"), "drills", ["deck_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_drills_deck_id"), table_name="drills")
    op.drop_table("drills")
    op.drop_index(op.f("ix_drill_decks_user_id"), table_name="drill_decks")
    op.drop_index(op.f("ix_drill_decks_setup_version_id"), table_name="drill_decks")
    op.drop_table("drill_decks")
    op.drop_index(op.f("ix_drill_plans_session_id"), table_name="drill_plans")
    op.drop_table("drill_plans")
