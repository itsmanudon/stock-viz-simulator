"""A5.4 trade plans (M10.3): trade_plans, plan links, drill_plans and
replay_journals absorbed and archived.

Revision ID: b5d4a7e1c902
Revises: 6ad74b7c4b5b
Create Date: 2026-11-26 18:00:00.000000

- ``trade_plans`` (``models/trade_plan.py``): one table for paper, replay,
  drill and (A5.5) imported plans. Locks at the first fill it covers.
- ``trades.trade_plan_id`` and ``pending_orders.trade_plan_id`` (nullable,
  ``ON DELETE SET NULL``): the plan a fill (or an order's fill) belongs to.
- **Data:** every replay session with a ``drill_plans`` or ``replay_journals``
  row becomes one ``trade_plans`` row keyed on the session (``source`` drill
  when the session is a drill's, else replay): the drill plan's entry, stop,
  size and note (``why``), the journal's thesis, invalidation, expected bars,
  confidence and reflection (``notes``). ``locked_at`` keeps the stored lock
  (or the first fill, which the old code set on the next read). A row first
  written after the session's first fill (wall-clock, ``replay_fills.created_at``)
  is ``written_after_entry`` and not locked. Sessions that already have a
  plan are skipped, so the copy is idempotent.
- ``drill_plans`` and ``replay_journals`` move to the ``archive`` schema with
  their rows, primary keys and indexes (the A0 pattern); their keys to
  ``replay_sessions`` are dropped so the archive never blocks deleting a
  session. Dropping them is a later batch (A5 design note, question 12).

Downgrade refuses while any paper or imported plan exists (older code has
nowhere to keep them; it names how many). Otherwise it moves the archived
tables back (keys restored NOT VALID), writes the replay and drill plans back
into them (upsert by session, so edits made since the upgrade survive), and
drops the links and ``trade_plans``.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b5d4a7e1c902"
down_revision: str | None = "6ad74b7c4b5b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ARCHIVED = {
    "drill_plans": "drill_plans_session_id_fkey",
    "replay_journals": "replay_journals_session_id_fkey",
}

COPY = """
INSERT INTO trade_plans (
    user_id, portfolio_id, replay_session_id, instrument_id, source, side,
    planned_entry, planned_stop, planned_target, planned_size,
    why, thesis_text, invalidation, horizon_bars, confidence, notes, tags,
    status, locked_at, first_fill_at, written_after_entry, created_at, updated_at
)
SELECT
    s.user_id, NULL, s.id, s.instrument_id,
    CASE WHEN EXISTS (SELECT 1 FROM drills d WHERE d.session_id = s.id)
         THEN 'drill' ELSE 'replay' END,
    COALESCE(dp.side, 'long'),
    dp.planned_entry, dp.planned_stop, NULL, dp.planned_size,
    dp.note, rj.thesis, rj.invalidation, rj.expected_holding_bars, rj.confidence,
    rj.reflection, '[]'::jsonb,
    CASE
        WHEN s.status IN ('completed', 'cancelled') AND ff.first_at IS NOT NULL THEN 'closed'
        WHEN s.status IN ('completed', 'cancelled') THEN 'cancelled'
        WHEN ff.first_at IS NOT NULL THEN 'active'
        ELSE 'open'
    END,
    CASE
        WHEN ff.first_at IS NULL THEN NULL
        WHEN LEAST(dp.created_at, rj.created_at) > ff.first_created THEN NULL
        ELSE COALESCE(LEAST(dp.locked_at, rj.locked_at), ff.first_at)
    END,
    ff.first_at,
    COALESCE(ff.first_at IS NOT NULL
             AND LEAST(dp.created_at, rj.created_at) > ff.first_created, false),
    LEAST(dp.created_at, rj.created_at),
    GREATEST(dp.updated_at, rj.updated_at)
FROM replay_sessions s
LEFT JOIN drill_plans dp ON dp.session_id = s.id
LEFT JOIN replay_journals rj ON rj.session_id = s.id
LEFT JOIN (
    SELECT session_id, MIN(evaluated_at) AS first_at, MIN(created_at) AS first_created
    FROM replay_fills GROUP BY session_id
) ff ON ff.session_id = s.id
WHERE (dp.id IS NOT NULL OR rj.id IS NOT NULL)
  AND NOT EXISTS (SELECT 1 FROM trade_plans tp WHERE tp.replay_session_id = s.id)
"""

WRITE_BACK_DRILLS = """
INSERT INTO drill_plans (session_id, side, planned_entry, planned_stop, planned_size,
                         note, locked_at, created_at, updated_at)
SELECT replay_session_id, 'long', planned_entry, planned_stop, planned_size, why,
       COALESCE(locked_at, first_fill_at), created_at, updated_at
FROM trade_plans
WHERE source = 'drill' AND planned_entry IS NOT NULL
  AND planned_stop IS NOT NULL AND planned_size IS NOT NULL
ON CONFLICT (session_id) DO UPDATE SET
    planned_entry = EXCLUDED.planned_entry, planned_stop = EXCLUDED.planned_stop,
    planned_size = EXCLUDED.planned_size, note = EXCLUDED.note,
    locked_at = EXCLUDED.locked_at, updated_at = EXCLUDED.updated_at
"""

WRITE_BACK_JOURNALS = """
INSERT INTO replay_journals (session_id, thesis, invalidation, expected_holding_bars,
                             confidence, reflection, locked_at, created_at, updated_at)
SELECT replay_session_id, thesis_text, invalidation, horizon_bars, confidence, notes,
       COALESCE(locked_at, first_fill_at), created_at, updated_at
FROM trade_plans
WHERE source = 'replay'
   OR (source = 'drill' AND (thesis_text IS NOT NULL OR invalidation IS NOT NULL
       OR horizon_bars IS NOT NULL OR confidence IS NOT NULL OR notes IS NOT NULL))
ON CONFLICT (session_id) DO UPDATE SET
    thesis = EXCLUDED.thesis, invalidation = EXCLUDED.invalidation,
    expected_holding_bars = EXCLUDED.expected_holding_bars,
    confidence = EXCLUDED.confidence, reflection = EXCLUDED.reflection,
    locked_at = EXCLUDED.locked_at, updated_at = EXCLUDED.updated_at
"""


def upgrade() -> None:
    op.create_table(
        "trade_plans",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("portfolio_id", sa.Integer(), nullable=True),
        sa.Column("replay_session_id", sa.Integer(), nullable=True),
        sa.Column("instrument_id", sa.BigInteger(), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("side", sa.String(length=8), server_default="long", nullable=False),
        sa.Column("planned_entry", sa.Numeric(18, 6), nullable=True),
        sa.Column("planned_stop", sa.Numeric(18, 6), nullable=True),
        sa.Column("planned_target", sa.Numeric(18, 6), nullable=True),
        sa.Column("planned_size", sa.Numeric(20, 6), nullable=True),
        sa.Column("setup_version_id", sa.Integer(), nullable=True),
        sa.Column("thesis_id", sa.Integer(), nullable=True),
        sa.Column("thesis_text", sa.Text(), nullable=True),
        sa.Column("why", sa.Text(), nullable=True),
        sa.Column("invalidation", sa.Text(), nullable=True),
        sa.Column("horizon_bars", sa.Integer(), nullable=True),
        sa.Column("confidence", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("tags", postgresql.JSONB(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="open", nullable=False),
        sa.Column("locked_at", sa.DateTime(), nullable=True),
        sa.Column("first_fill_at", sa.DateTime(), nullable=True),
        sa.Column(
            "written_after_entry", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "source IN ('paper', 'replay', 'drill', 'imported')", name="ck_trade_plans_source"
        ),
        sa.CheckConstraint("side IN ('long', 'short')", name="ck_trade_plans_side"),
        sa.CheckConstraint(
            "status IN ('open', 'active', 'closed', 'cancelled')", name="ck_trade_plans_status"
        ),
        sa.CheckConstraint(
            "(planned_entry IS NULL OR planned_entry > 0) "
            "AND (planned_stop IS NULL OR planned_stop > 0) "
            "AND (planned_target IS NULL OR planned_target > 0) "
            "AND (planned_size IS NULL OR planned_size > 0)",
            name="ck_trade_plans_positive",
        ),
        sa.CheckConstraint(
            "(source IN ('replay', 'drill') AND replay_session_id IS NOT NULL) "
            "OR (source IN ('paper', 'imported') AND portfolio_id IS NOT NULL)",
            name="ck_trade_plans_home",
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR confidence BETWEEN 1 AND 5", name="ck_trade_plans_confidence"
        ),
        sa.CheckConstraint(
            "NOT (written_after_entry AND locked_at IS NOT NULL)",
            name="ck_trade_plans_lock_or_after",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["portfolio_id"], ["portfolios.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["replay_session_id"], ["replay_sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["instrument_id"], ["instruments.id"]),
        sa.ForeignKeyConstraint(["setup_version_id"], ["setup_versions.id"]),
        sa.ForeignKeyConstraint(["thesis_id"], ["theses.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("replay_session_id"),
    )
    for column in ("user_id", "portfolio_id", "instrument_id", "setup_version_id", "thesis_id"):
        op.create_index(op.f(f"ix_trade_plans_{column}"), "trade_plans", [column])

    for table in ("trades", "pending_orders"):
        op.add_column(table, sa.Column("trade_plan_id", sa.Integer(), nullable=True))
        op.create_foreign_key(
            f"fk_{table}_trade_plan_id",
            table,
            "trade_plans",
            ["trade_plan_id"],
            ["id"],
            ondelete="SET NULL",
        )
        op.create_index(op.f(f"ix_{table}_trade_plan_id"), table, ["trade_plan_id"])

    op.execute(COPY)

    op.execute("CREATE SCHEMA IF NOT EXISTS archive")
    for table, key in ARCHIVED.items():
        op.execute(f"ALTER TABLE public.{table} SET SCHEMA archive")
        op.execute(f"ALTER TABLE archive.{table} DROP CONSTRAINT IF EXISTS {key}")


def downgrade() -> None:
    bind = op.get_bind()
    kept = bind.execute(
        sa.text("SELECT count(*) FROM trade_plans WHERE source IN ('paper', 'imported')")
    ).scalar_one()
    if kept:
        raise RuntimeError(
            f"Refusing to downgrade: {kept} paper or imported trade plans exist, and the older "
            "schema has nowhere to keep them. Export or delete them first."
        )
    for table, key in ARCHIVED.items():
        op.execute(f"ALTER TABLE archive.{table} SET SCHEMA public")
        op.execute(
            f"ALTER TABLE public.{table} ADD CONSTRAINT {key} FOREIGN KEY (session_id) "
            "REFERENCES replay_sessions(id) ON DELETE CASCADE NOT VALID"
        )
    op.execute(WRITE_BACK_DRILLS)
    op.execute(WRITE_BACK_JOURNALS)

    for table in ("pending_orders", "trades"):
        op.drop_index(op.f(f"ix_{table}_trade_plan_id"), table_name=table)
        op.drop_constraint(f"fk_{table}_trade_plan_id", table, type_="foreignkey")
        op.drop_column(table, "trade_plan_id")
    for column in ("thesis_id", "setup_version_id", "instrument_id", "portfolio_id", "user_id"):
        op.drop_index(op.f(f"ix_trade_plans_{column}"), table_name="trade_plans")
    op.drop_table("trade_plans")
