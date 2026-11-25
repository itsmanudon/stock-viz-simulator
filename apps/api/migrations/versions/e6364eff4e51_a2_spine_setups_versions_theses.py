"""A2.2: the spine. setups, setup_versions (immutable), theses, and a nullable
setup_version_id on saved_screens, alerts and experiment_runs. Additive only.

setups.forked_from_version_id and setup_versions.setup_id point at each other,
so the fork key is added after both tables exist.

Revision ID: e6364eff4e51
Revises: 85e6a9572a9f
Create Date: 2026-11-25 22:49:15.397143

"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op


revision: str = "e6364eff4e51"
down_revision: str | None = "85e6a9572a9f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "setups",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(length=120), nullable=False),
        sa.Column("kind", sqlmodel.sql.sqltypes.AutoString(length=16), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_preset", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("forked_from_version_id", sa.Integer(), nullable=True),
        sa.Column("preset_key", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("archived_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "kind IN ('screen', 'alert', 'strategy', 'checklist')", name="ck_setups_kind"
        ),
        sa.CheckConstraint(
            "(is_preset AND user_id IS NULL) OR (NOT is_preset AND user_id IS NOT NULL)",
            name="ck_setups_preset_owner",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("preset_key"),
    )
    op.create_index(op.f("ix_setups_user_id"), "setups", ["user_id"], unique=False)
    op.create_table(
        "theses",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("instrument_id", sa.Integer(), nullable=False),
        sa.Column("title", sqlmodel.sql.sqltypes.AutoString(length=160), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("kill_rule_text", sa.Text(), nullable=True),
        sa.Column("kill_rule_hash", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=True),
        sa.Column("status", sqlmodel.sql.sqltypes.AutoString(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("status IN ('open', 'invalidated', 'closed')", name="ck_theses_status"),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["instruments.id"],
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_theses_instrument_id"), "theses", ["instrument_id"], unique=False)
    op.create_index(op.f("ix_theses_user_id"), "theses", ["user_id"], unique=False)
    op.create_table(
        "setup_versions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("setup_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("rule_text", sa.Text(), nullable=False),
        sa.Column("canonical_text", sa.Text(), nullable=False),
        sa.Column("rule_hash", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False),
        sa.Column("timeframe", sqlmodel.sql.sqltypes.AutoString(length=16), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["setup_id"], ["setups.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("setup_id", "rule_hash", name="uq_setup_versions_setup_rule_hash"),
        sa.UniqueConstraint("setup_id", "version", name="uq_setup_versions_setup_version"),
    )
    op.create_index(
        op.f("ix_setup_versions_rule_hash"), "setup_versions", ["rule_hash"], unique=False
    )
    op.create_index(
        op.f("ix_setup_versions_setup_id"), "setup_versions", ["setup_id"], unique=False
    )
    op.create_foreign_key(
        "fk_setups_forked_from_version_id",
        "setups",
        "setup_versions",
        ["forked_from_version_id"],
        ["id"],
    )
    op.add_column("alerts", sa.Column("setup_version_id", sa.Integer(), nullable=True))
    op.create_index(
        op.f("ix_alerts_setup_version_id"), "alerts", ["setup_version_id"], unique=False
    )
    op.create_foreign_key(
        "alerts_setup_version_id_fkey", "alerts", "setup_versions", ["setup_version_id"], ["id"]
    )
    op.add_column("experiment_runs", sa.Column("setup_version_id", sa.Integer(), nullable=True))
    op.create_index(
        op.f("ix_experiment_runs_setup_version_id"),
        "experiment_runs",
        ["setup_version_id"],
        unique=False,
    )
    op.create_foreign_key(
        "experiment_runs_setup_version_id_fkey",
        "experiment_runs",
        "setup_versions",
        ["setup_version_id"],
        ["id"],
    )
    op.add_column("saved_screens", sa.Column("setup_version_id", sa.Integer(), nullable=True))
    op.create_index(
        op.f("ix_saved_screens_setup_version_id"),
        "saved_screens",
        ["setup_version_id"],
        unique=False,
    )
    op.create_foreign_key(
        "saved_screens_setup_version_id_fkey",
        "saved_screens",
        "setup_versions",
        ["setup_version_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("saved_screens_setup_version_id_fkey", "saved_screens", type_="foreignkey")
    op.drop_index(op.f("ix_saved_screens_setup_version_id"), table_name="saved_screens")
    op.drop_column("saved_screens", "setup_version_id")
    op.drop_constraint(
        "experiment_runs_setup_version_id_fkey", "experiment_runs", type_="foreignkey"
    )
    op.drop_index(op.f("ix_experiment_runs_setup_version_id"), table_name="experiment_runs")
    op.drop_column("experiment_runs", "setup_version_id")
    op.drop_constraint("alerts_setup_version_id_fkey", "alerts", type_="foreignkey")
    op.drop_index(op.f("ix_alerts_setup_version_id"), table_name="alerts")
    op.drop_column("alerts", "setup_version_id")
    op.drop_constraint("fk_setups_forked_from_version_id", "setups", type_="foreignkey")
    op.drop_index(op.f("ix_setup_versions_setup_id"), table_name="setup_versions")
    op.drop_index(op.f("ix_setup_versions_rule_hash"), table_name="setup_versions")
    op.drop_table("setup_versions")
    op.drop_index(op.f("ix_theses_user_id"), table_name="theses")
    op.drop_index(op.f("ix_theses_instrument_id"), table_name="theses")
    op.drop_table("theses")
    op.drop_index(op.f("ix_setups_user_id"), table_name="setups")
    op.drop_table("setups")
