"""A2.3: rule alerts, nightly screen runs, notification delivery (additive).

- ``alerts``: ``kind = 'rule'`` must name a setup version (check).
- ``screen_runs``: a setup version's members per session.
- ``saved_screens.notify_on_change`` (default false).
- ``notifications.data``: structured detail (entries and exits).
- ``notification_channels`` and ``delivery_attempts``: webhook, email and
  Telegram settings and the outbox of sends.

The downgrade removes ``rule`` alerts (and, by cascade, their events): the
code before A2.3 cannot word or judge them.

Revision ID: 6e6c8aed50fb
Revises: e6364eff4e51
Create Date: 2026-11-25 23:21:24.873158

"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "6e6c8aed50fb"
down_revision: str | None = "e6364eff4e51"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "notification_channels",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("channel", sqlmodel.sql.sqltypes.AutoString(length=16), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "config",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("secret", sa.Text(), nullable=True),
        sa.Column(
            "muted_categories",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("enabled_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "channel IN ('webhook', 'email', 'telegram')", name="ck_notification_channels_channel"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "channel", name="uq_notification_channels_user_channel"),
    )
    op.create_index(
        op.f("ix_notification_channels_user_id"), "notification_channels", ["user_id"], unique=False
    )
    op.create_table(
        "delivery_attempts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("notification_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("channel", sqlmodel.sql.sqltypes.AutoString(length=16), nullable=False),
        sa.Column("status", sqlmodel.sql.sqltypes.AutoString(length=16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.Column("dead_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["notification_id"], ["notifications.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "notification_id", "channel", name="uq_delivery_attempts_notification_channel"
        ),
    )
    op.create_index(
        op.f("ix_delivery_attempts_notification_id"),
        "delivery_attempts",
        ["notification_id"],
        unique=False,
    )
    op.create_index(
        "ix_delivery_attempts_status_next",
        "delivery_attempts",
        ["status", "next_attempt_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_delivery_attempts_user_id"), "delivery_attempts", ["user_id"], unique=False
    )
    op.create_table(
        "screen_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("setup_version_id", sa.Integer(), nullable=False),
        sa.Column("session_date", sa.Date(), nullable=False),
        sa.Column("venue", sqlmodel.sql.sqltypes.AutoString(length=16), nullable=False),
        sa.Column("universe", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False),
        sa.Column(
            "members",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("member_count", sa.Integer(), nullable=False),
        sa.Column("evaluated", sa.Integer(), nullable=False),
        sa.Column("not_evaluated", sa.Integer(), nullable=False),
        sa.Column(
            "sessions",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=True,
        ),
        sa.Column("computed_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["setup_version_id"], ["setup_versions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "setup_version_id", "session_date", name="uq_screen_runs_version_session"
        ),
    )
    op.create_index(
        op.f("ix_screen_runs_setup_version_id"), "screen_runs", ["setup_version_id"], unique=False
    )
    op.create_check_constraint(
        "ck_alerts_rule_has_version", "alerts", "kind <> 'rule' OR setup_version_id IS NOT NULL"
    )
    op.add_column(
        "notifications",
        sa.Column(
            "data",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=True,
        ),
    )
    op.add_column(
        "saved_screens",
        sa.Column(
            "notify_on_change", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
    )


def downgrade() -> None:
    op.drop_column("saved_screens", "notify_on_change")
    op.drop_column("notifications", "data")
    op.drop_constraint("ck_alerts_rule_has_version", "alerts", type_="check")
    op.execute("DELETE FROM alerts WHERE kind = 'rule'")
    op.drop_index(op.f("ix_screen_runs_setup_version_id"), table_name="screen_runs")
    op.drop_table("screen_runs")
    op.drop_index(op.f("ix_delivery_attempts_user_id"), table_name="delivery_attempts")
    op.drop_index("ix_delivery_attempts_status_next", table_name="delivery_attempts")
    op.drop_index(op.f("ix_delivery_attempts_notification_id"), table_name="delivery_attempts")
    op.drop_table("delivery_attempts")
    op.drop_index(op.f("ix_notification_channels_user_id"), table_name="notification_channels")
    op.drop_table("notification_channels")
