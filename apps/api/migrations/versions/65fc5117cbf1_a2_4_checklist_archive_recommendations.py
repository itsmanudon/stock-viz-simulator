"""checklist scores and evidence; archive recommendations (A2.4)

Revision ID: 65fc5117cbf1
Revises: 6e6c8aed50fb
Create Date: 2026-11-26 10:00:00.000000

The Checklist replaces the 7-vote Signals (M4.4). Adds ``checklist_scores``
(one row per instrument and session, the nightly ``checklist`` job) and
``checklist_evidence`` (the weekly study per dimension setup version).

The Signals engine is removed in the same batch. Its table is not dropped:
``recommendations`` moves to the ``archive`` schema with its rows, primary
key, indexes and sequence, so nothing is lost. Its keys to ``symbols`` and
``instruments`` and its instrument trigger are dropped, so the archive never
blocks a change to a live table. The downgrade moves it back and restores
them (the keys as NOT VALID, since archived rows may point at rows deleted
since). Same pattern as ``89b9ba1b46b5`` (comments) and ``ea0040711437``
(legacy news). Dropping the archive is the owner's call.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "65fc5117cbf1"
down_revision: str | None = "6e6c8aed50fb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Read from pg_constraint on a database at 6e6c8aed50fb.
LIVE_KEYS = {
    "recommendations_ticker_fkey": "FOREIGN KEY (ticker) REFERENCES symbols(ticker)",
    "fk_recommendations_instrument_id": "FOREIGN KEY (instrument_id) REFERENCES instruments(id)",
}

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "checklist_scores",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("instrument_id", sa.Integer(), nullable=False),
        sa.Column("session_date", sa.Date(), nullable=False),
        sa.Column("dimensions", JSON, nullable=False),
        sa.Column("met_count", sa.Integer(), nullable=False),
        sa.Column("evaluated_count", sa.Integer(), nullable=False),
        sa.Column("computed_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["instrument_id"], ["instruments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "instrument_id", "session_date", name="uq_checklist_scores_instrument_session"
        ),
    )
    op.create_index(
        "ix_checklist_scores_instrument_id", "checklist_scores", ["instrument_id"], unique=False
    )
    op.create_index(
        "ix_checklist_scores_session_date", "checklist_scores", ["session_date"], unique=False
    )
    op.create_table(
        "checklist_evidence",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("setup_version_id", sa.Integer(), nullable=False),
        sa.Column("dimension", sa.String(length=32), nullable=False),
        sa.Column("scope", sa.String(length=16), nullable=False),
        sa.Column("universe", sa.String(length=64), nullable=False),
        sa.Column("point_in_time", sa.Boolean(), nullable=False),
        sa.Column("survivorship_biased", sa.Boolean(), nullable=False),
        sa.Column("window_start", sa.Date(), nullable=False),
        sa.Column("window_end", sa.Date(), nullable=False),
        sa.Column("horizon", sa.Integer(), nullable=False),
        sa.Column("symbols", sa.Integer(), nullable=False),
        sa.Column("n_events", sa.Integer(), nullable=False),
        sa.Column("overlapping_skipped", sa.Integer(), nullable=False),
        sa.Column("mean_net_return", sa.Float(), nullable=True),
        sa.Column("base_rate", sa.Float(), nullable=True),
        sa.Column("mean_excess", sa.Float(), nullable=True),
        sa.Column("t_stat", sa.Float(), nullable=True),
        sa.Column("hit_rate", sa.Float(), nullable=True),
        sa.Column("grade", sa.String(length=16), nullable=False),
        sa.Column("fee_schedules", JSON, nullable=True),
        sa.Column("computed_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["setup_version_id"], ["setup_versions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "setup_version_id",
            "universe",
            "window_start",
            "window_end",
            "horizon",
            name="uq_checklist_evidence_version_window",
        ),
    )
    op.create_index(
        "ix_checklist_evidence_setup_version_id",
        "checklist_evidence",
        ["setup_version_id"],
        unique=False,
    )

    op.execute("CREATE SCHEMA IF NOT EXISTS archive")
    op.execute("ALTER TABLE public.recommendations SET SCHEMA archive")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_recommendations_instrument_id ON archive.recommendations"
    )
    for name in LIVE_KEYS:
        op.execute(f"ALTER TABLE archive.recommendations DROP CONSTRAINT IF EXISTS {name}")


def downgrade() -> None:
    op.execute("ALTER TABLE archive.recommendations SET SCHEMA public")
    for name, definition in LIVE_KEYS.items():
        op.execute(
            f"ALTER TABLE public.recommendations ADD CONSTRAINT {name} {definition} NOT VALID"
        )
    op.execute(
        "CREATE TRIGGER trg_recommendations_instrument_id BEFORE INSERT OR UPDATE OF ticker "
        "ON public.recommendations FOR EACH ROW EXECUTE FUNCTION stockviz_fill_instrument_id()"
    )

    op.drop_index("ix_checklist_evidence_setup_version_id", table_name="checklist_evidence")
    op.drop_table("checklist_evidence")
    op.drop_index("ix_checklist_scores_session_date", table_name="checklist_scores")
    op.drop_index("ix_checklist_scores_instrument_id", table_name="checklist_scores")
    op.drop_table("checklist_scores")
