"""A6.5 stream worker: the ``replayed`` feed and ``feed_streams``.

Revision ID: c8d3e5f7a9b2
Revises: b7c2d4e6f8a1
Create Date: 2026-11-27 12:00:00.000000

- ``intraday_bars.feed`` may be ``replayed``: minute bars the stream worker
  built from ``SimulatedFeed`` ticks. They sit beside the real feeds, never
  in place of them, and the best-feed default reads them last.
- ``feed_streams``: one row per stream the worker has run (``simulated``,
  later ``alpaca``): its state, the symbols it watches, the last tick and
  bar instants and its counters. Broker status reads it.

Additive. The downgrade refuses while a ``replayed`` bar is stored.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c8d3e5f7a9b2"
down_revision: str | None = "b7c2d4e6f8a1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD = "feed IN ('iex', 'sip', 'kite', 'file')"
NEW = "feed IN ('iex', 'sip', 'kite', 'file', 'replayed')"


def upgrade() -> None:
    # On PostgreSQL a constraint on the partitioned parent applies to every
    # partition, so one drop and one add cover them all.
    op.drop_constraint("ck_intraday_bars_feed", "intraday_bars", type_="check")
    op.create_check_constraint("ck_intraday_bars_feed", "intraday_bars", NEW)
    op.create_table(
        "feed_streams",
        sa.Column("name", sa.String(length=24), primary_key=True),
        sa.Column("label", sa.String(length=40), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("symbols", sa.JSON(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("stopped_at", sa.DateTime(), nullable=True),
        sa.Column("last_tick_at", sa.DateTime(), nullable=True),
        sa.Column("last_bar_at", sa.DateTime(), nullable=True),
        sa.Column("bars_written", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("alerts_fired", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.String(length=200), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "state IN ('streaming', 'closed', 'error')", name="ck_feed_streams_state"
        ),
    )


def downgrade() -> None:
    bind = op.get_bind()
    count = bind.execute(sa.text("SELECT count(*) FROM intraday_bars WHERE feed = 'replayed'"))
    if count.scalar_one():
        raise RuntimeError(
            "replayed intraday bars are stored; delete them "
            "(DELETE FROM intraday_bars WHERE feed = 'replayed') before downgrading"
        )
    op.drop_table("feed_streams")
    op.drop_constraint("ck_intraday_bars_feed", "intraday_bars", type_="check")
    op.create_check_constraint("ck_intraday_bars_feed", "intraday_bars", OLD)
