"""A5.5's migration (``c9d2e4f6a8b1``) on PostgreSQL: up, down, up.

The upgrade adds ``journal_entries`` and ``journal_entry_fills``. With an
entry holding the user's notes the downgrade refuses and changes nothing;
entries without text are derived, so it drops both, and the upgrade runs
again.
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
BEFORE = "e3a1c5d7f902"
THIS = "c9d2e4f6a8b1"


@pytest.fixture(autouse=True)
def _keep_logging() -> Iterator[None]:
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


def test_a55_journal_entries_migration_up_down_up(monkeypatch) -> None:
    with scratch_alembic_engine() as engine:
        monkeypatch.setenv("DATABASE_URL", engine.url.render_as_string(hide_password=False))
        get_settings.cache_clear()
        try:
            config = Config(str(API_ROOT / "alembic.ini"))
            config.set_main_option("script_location", str(API_ROOT / "migrations"))
            command.upgrade(config, BEFORE)
            assert "journal_entries" not in inspect(engine).get_table_names()
            command.upgrade(config, THIS)
            assert {"journal_entries", "journal_entry_fills"} <= set(
                inspect(engine).get_table_names()
            )
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO symbols (ticker, name, is_active, currency, created_at) "
                        "VALUES ('TCS.NS', 'TCS', true, 'INR', now())"
                    )
                )
                uid = conn.execute(
                    text(
                        "INSERT INTO users (email, public_profile, created_at) "
                        "VALUES ('j@x.dev', false, now()) RETURNING id"
                    )
                ).scalar_one()
                pid = conn.execute(
                    text(
                        "INSERT INTO portfolios (user_id, name, kind, is_default, cash_tracked, "
                        "cash_balance, base_currency, opening_nav, created_at) VALUES "
                        "(:u, 'P', 'paper', true, true, 0, 'INR', 0, now()) RETURNING id"
                    ),
                    {"u": uid},
                ).scalar_one()
                iid = conn.execute(
                    text("SELECT instrument_id FROM instrument_identifiers WHERE value='TCS.NS'")
                ).scalar_one()
                entry_sql = (
                    "INSERT INTO journal_entries (user_id, source, portfolio_id, instrument_id, "
                    "entry_key, status, opened_at, review_notes, created_at, updated_at) VALUES "
                    "(:u, 'paper', :p, :i, :k, 'closed', now(), :n, now(), now()) RETURNING id"
                )
                params = {"u": uid, "p": pid, "i": iid}
                noted = conn.execute(
                    text(entry_sql), {**params, "k": "paper:1:t1", "n": "kept"}
                ).scalar_one()
                conn.execute(text(entry_sql), {**params, "k": "paper:1:t2", "n": None})
            # One key per user.
            with pytest.raises(Exception, match="uq_journal_entries_user_key"), engine.begin() as c:
                c.execute(text(entry_sql), {**params, "k": "paper:1:t2", "n": None})
            # A replay entry needs its session, not a book.
            with pytest.raises(Exception, match="ck_journal_entries_home"), engine.begin() as c:
                c.execute(
                    text(
                        "INSERT INTO journal_entries (user_id, source, portfolio_id, "
                        "instrument_id, entry_key, status, opened_at, created_at, updated_at) "
                        "VALUES (:u, 'replay', :p, :i, 'r', 'open', now(), now(), now())"
                    ),
                    params,
                )
            with pytest.raises(Exception, match="notes or tags"):
                command.downgrade(config, BEFORE)
            assert "journal_entries" in inspect(engine).get_table_names()
            with engine.begin() as conn:
                conn.execute(
                    text("UPDATE journal_entries SET review_notes = NULL WHERE id = :e"),
                    {"e": noted},
                )
            command.downgrade(config, BEFORE)
            tables = set(inspect(engine).get_table_names())
            assert "journal_entries" not in tables and "journal_entry_fills" not in tables
            command.upgrade(config, "head")
            assert "journal_entries" in inspect(engine).get_table_names()
        finally:
            engine.dispose()
            get_settings.cache_clear()
