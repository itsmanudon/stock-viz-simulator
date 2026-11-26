"""A6.4 intraday rules: setup version timeframe and feed, alert state on instants.

Revision ID: b7c2d4e6f8a1
Revises: a6b1c3d5e7f9
Create Date: 2026-11-27 00:30:00.000000

- ``setup_versions.feed`` (``auto`` | ``iex`` | ``sip`` | ``kite`` | ``file``,
  default ``auto`` = the best stored feed), and checks on ``timeframe``
  (``daily`` or ``1m`` ... ``60m``) and ``feed``. The unique key
  ``(setup_id, rule_hash)`` becomes ``(setup_id, rule_hash, timeframe,
  feed)``: the same rule on 5-minute bars is another version.
- ``alerts.last_bar_at`` / ``last_fired_bar_at``: intraday rule alerts keep
  their state per bar instant (naive UTC, the bar's open).
- ``alert_events.bar_at`` and ``feed``: the bar an intraday firing judged and
  the feed it came from. The dedupe key stays unique (``<alert>:<bar open>``).

Additive. The downgrade refuses while an intraday setup version exists (old
code would judge it on daily bars), then drops the columns and restores the
old key.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b7c2d4e6f8a1"
down_revision: str | None = "a6b1c3d5e7f9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TIMEFRAMES = "('daily', '1m', '5m', '15m', '30m', '60m')"
FEEDS = "('auto', 'iex', 'sip', 'kite', 'file')"


def upgrade() -> None:
    op.add_column(
        "setup_versions",
        sa.Column("feed", sa.String(length=8), nullable=False, server_default="auto"),
    )
    op.create_check_constraint(
        "ck_setup_versions_timeframe", "setup_versions", f"timeframe IN {TIMEFRAMES}"
    )
    op.create_check_constraint("ck_setup_versions_feed", "setup_versions", f"feed IN {FEEDS}")
    op.drop_constraint("uq_setup_versions_setup_rule_hash", "setup_versions", type_="unique")
    op.create_unique_constraint(
        "uq_setup_versions_setup_rule_hash",
        "setup_versions",
        ["setup_id", "rule_hash", "timeframe", "feed"],
    )
    op.add_column("alerts", sa.Column("last_bar_at", sa.DateTime(), nullable=True))
    op.add_column("alerts", sa.Column("last_fired_bar_at", sa.DateTime(), nullable=True))
    op.add_column("alert_events", sa.Column("bar_at", sa.DateTime(), nullable=True))
    op.add_column("alert_events", sa.Column("feed", sa.String(length=8), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    count = bind.execute(
        sa.text("SELECT count(*) FROM setup_versions WHERE timeframe <> 'daily' OR feed <> 'auto'")
    ).scalar()
    if count:
        raise RuntimeError(
            f"{count} intraday setup version(s) exist; the code before A6.4 would judge them "
            "on daily bars. Archive or delete them first."
        )
    op.drop_column("alert_events", "feed")
    op.drop_column("alert_events", "bar_at")
    op.drop_column("alerts", "last_fired_bar_at")
    op.drop_column("alerts", "last_bar_at")
    op.drop_constraint("uq_setup_versions_setup_rule_hash", "setup_versions", type_="unique")
    op.create_unique_constraint(
        "uq_setup_versions_setup_rule_hash", "setup_versions", ["setup_id", "rule_hash"]
    )
    op.drop_constraint("ck_setup_versions_feed", "setup_versions", type_="check")
    op.drop_constraint("ck_setup_versions_timeframe", "setup_versions", type_="check")
    op.drop_column("setup_versions", "feed")
