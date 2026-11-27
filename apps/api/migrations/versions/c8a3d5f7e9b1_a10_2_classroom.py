"""A10.2 classroom cohorts and auto-graded drill assignments.

Revision ID: c8a3d5f7e9b1
Revises: b7e2f4a6c8d1
Create Date: 2026-11-27 14:00:00.000000

- ``cohorts`` (owner, name, unique invite code), ``cohort_members`` (who
  joined and consented), ``cohort_assignments`` (a drill-deck recipe and its
  rubric), ``assignment_decks`` (each student's deck for an assignment).

Additive; everything cascades from its cohort or user. The downgrade refuses
while any cohort exists.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c8a3d5f7e9b1"
down_revision: str | None = "b7e2f4a6c8d1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "cohorts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "owner_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("invite_code", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("archived_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("invite_code"),
    )
    op.create_index("ix_cohorts_owner_id", "cohorts", ["owner_id"])
    op.create_table(
        "cohort_members",
        sa.Column(
            "cohort_id",
            sa.Integer(),
            sa.ForeignKey("cohorts.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("joined_at", sa.DateTime(), nullable=False),
        sa.Column("consented_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "cohort_assignments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "cohort_id",
            sa.Integer(),
            sa.ForeignKey("cohorts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("recipe", sa.JSON(), nullable=False),
        sa.Column("min_followed_pct", sa.Integer(), nullable=False),
        sa.Column("due_on", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_cohort_assignments_cohort_id", "cohort_assignments", ["cohort_id"])
    op.create_table(
        "assignment_decks",
        sa.Column(
            "assignment_id",
            sa.Integer(),
            sa.ForeignKey("cohort_assignments.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column(
            "deck_id",
            sa.Integer(),
            sa.ForeignKey("drill_decks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("deck_id", name="uq_assignment_decks_deck"),
    )


def downgrade() -> None:
    conn = op.get_bind()
    count = conn.execute(sa.text("SELECT count(*) FROM cohorts")).scalar_one()
    if count:
        raise RuntimeError(f"{count} cohorts are stored; delete them before downgrading")
    op.drop_table("assignment_decks")
    op.drop_index("ix_cohort_assignments_cohort_id", table_name="cohort_assignments")
    op.drop_table("cohort_assignments")
    op.drop_table("cohort_members")
    op.drop_index("ix_cohorts_owner_id", table_name="cohorts")
    op.drop_table("cohorts")
