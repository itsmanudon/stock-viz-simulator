"""A4.7's migration (``53b66a2e2ec2``) on PostgreSQL: up, down, up.

``drill_decks``, ``drills`` and ``drill_plans`` arrive with their checks;
deleting a deck cascades to its drills, deleting a replay session cascades to
its drill and plan; the downgrade drops the three tables.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text

from stockviz.settings import get_settings
from tests.pg_scratch import postgres_admin_url, scratch_alembic_engine

pytestmark = pytest.mark.skipif(
    postgres_admin_url() is None, reason="DATABASE_URL is not PostgreSQL"
)

API_ROOT = Path(__file__).resolve().parents[1]
BEFORE = "a6c4e2f8b913"
# A5.4 (b5d4a7e1c902) archives drill_plans; this test checks A4.7's own step.
AFTER = "6ad74b7c4b5b"


@pytest.fixture(autouse=True)
def _keep_logging() -> Iterator[None]:
    """``migrations/env.py`` runs ``fileConfig``; put logging back afterwards."""
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    disabled = {
        name: lg.disabled
        for name, lg in logging.root.manager.loggerDict.items()
        if isinstance(lg, logging.Logger)
    }
    yield
    root.handlers[:] = handlers
    root.setLevel(level)
    for name, lg in logging.root.manager.loggerDict.items():
        if isinstance(lg, logging.Logger):
            lg.disabled = disabled.get(name, False)


DRILL_TABLES = {"drill_decks", "drills", "drill_plans"}


def test_a47_drills_migration_up_down_up(monkeypatch) -> None:
    with scratch_alembic_engine() as engine:
        monkeypatch.setenv("DATABASE_URL", engine.url.render_as_string(hide_password=False))
        get_settings.cache_clear()
        try:
            config = Config(str(API_ROOT / "alembic.ini"))
            config.set_main_option("script_location", str(API_ROOT / "migrations"))
            command.upgrade(config, BEFORE)
            assert not DRILL_TABLES & set(inspect(engine).get_table_names())
            command.upgrade(config, AFTER)
            assert set(inspect(engine).get_table_names()) >= DRILL_TABLES
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO symbols (ticker, name, is_active, currency, created_at) "
                        "VALUES ('AAPL', 'Apple', true, 'USD', now())"
                    )
                )
                uid = conn.execute(
                    text(
                        "INSERT INTO users (email, public_profile, created_at) "
                        "VALUES ('a@x.dev', false, now()) RETURNING id"
                    )
                ).scalar_one()
                setup = conn.execute(
                    text(
                        "INSERT INTO setups (user_id, name, kind, is_preset, created_at) "
                        "VALUES (:u, 'Rules from drills', 'screen', false, now()) RETURNING id"
                    ),
                    {"u": uid},
                ).scalar_one()
                ver = conn.execute(
                    text(
                        "INSERT INTO setup_versions (setup_id, version, rule_text, "
                        "canonical_text, rule_hash, timeframe, created_at) VALUES (:s, 1, "
                        "'close > 1', 'close > 1', 'h', 'daily', now()) RETURNING id"
                    ),
                    {"s": setup},
                ).scalar_one()
                sid = conn.execute(
                    text(
                        "INSERT INTO replay_sessions (user_id, ticker, profile_name, "
                        "model_version, start_at, current_at, end_at, starting_cash, "
                        "cash_balance, status, created_at, updated_at) VALUES (:u, 'AAPL', "
                        "'legacy_close', 'v1', now(), now(), now(), 100000, 100000, 'active', "
                        "now(), now()) RETURNING id"
                    ),
                    {"u": uid},
                ).scalar_one()
                deck = conn.execute(
                    text(
                        "INSERT INTO drill_decks (user_id, name, setup_version_id, rule_text, "
                        "rule_hash, universe, from_date, to_date, k, lead_bars, follow_bars, "
                        "seed, triggers_found, triggers_eligible, lag_skipped, created_at) "
                        "VALUES (:u, 'd', :v, 'close > 1', 'h', '{}', '2020-01-01', "
                        "'2021-01-01', 5, 60, 40, 7, 9, 9, 0, now()) RETURNING id"
                    ),
                    {"u": uid, "v": ver},
                ).scalar_one()
                assert (
                    conn.execute(
                        text("SELECT anonymised FROM drill_decks WHERE id = :d"), {"d": deck}
                    ).scalar_one()
                    is True
                )
                conn.execute(
                    text(
                        "INSERT INTO drills (deck_id, position, session_id, ticker, trigger_at, "
                        "trigger_date, date_offset_weeks, created_at) VALUES (:d, 0, :s, "
                        "'AAPL', now(), '2020-06-01', 104, now())"
                    ),
                    {"d": deck, "s": sid},
                )
                conn.execute(
                    text(
                        "INSERT INTO drill_plans (session_id, planned_entry, planned_stop, "
                        "planned_size, created_at, updated_at) VALUES (:s, 10, 9, 5, now(), "
                        "now())"
                    ),
                    {"s": sid},
                )
            with pytest.raises(Exception, match="ck_drill_decks_k"), engine.begin() as conn:
                conn.execute(text("UPDATE drill_decks SET k = 26"))
            with pytest.raises(Exception, match="ck_drill_plans_side"), engine.begin() as conn:
                conn.execute(text("UPDATE drill_plans SET side = 'short'"))
            with engine.begin() as conn:
                conn.execute(text("DELETE FROM replay_sessions"))
                assert conn.execute(text("SELECT count(*) FROM drills")).scalar_one() == 0
                assert conn.execute(text("SELECT count(*) FROM drill_plans")).scalar_one() == 0
                conn.execute(text("DELETE FROM drill_decks"))

            command.downgrade(config, BEFORE)
            assert not DRILL_TABLES & set(inspect(engine).get_table_names())
            command.upgrade(config, AFTER)
            assert set(inspect(engine).get_table_names()) >= DRILL_TABLES
        finally:
            engine.dispose()
            get_settings.cache_clear()
