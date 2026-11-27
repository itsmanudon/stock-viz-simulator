"""A10.2's migration (``c8a3d5f7e9b1``) on PostgreSQL: up, down, up.

The downgrade refuses while a cohort exists.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text

from stockviz.settings import get_settings
from tests.pg_scratch import postgres_admin_url, scratch_alembic_engine
from tests.test_intraday_migration import _keep_logging  # noqa: F401

pytestmark = pytest.mark.skipif(
    postgres_admin_url() is None, reason="DATABASE_URL is not PostgreSQL"
)

API_ROOT = Path(__file__).resolve().parents[1]
BEFORE = "b7e2f4a6c8d1"
THIS = "c8a3d5f7e9b1"


def test_a102_migration_up_down_up(monkeypatch) -> None:
    with scratch_alembic_engine() as engine:
        monkeypatch.setenv("DATABASE_URL", engine.url.render_as_string(hide_password=False))
        get_settings.cache_clear()
        try:
            config = Config(str(API_ROOT / "alembic.ini"))
            config.set_main_option("script_location", str(API_ROOT / "migrations"))
            command.upgrade(config, THIS)
            with engine.begin() as conn:
                uid = conn.execute(text(
                    "INSERT INTO users (email, public_profile, created_at) "
                    "VALUES ('t@x.dev', false, now()) RETURNING id"
                )).scalar_one()  # fmt: skip
                conn.execute(text(
                    "INSERT INTO cohorts (owner_id, name, invite_code, created_at) "
                    "VALUES (:u, 'c', 'ABCDEFGH', now())"
                ), {"u": uid})  # fmt: skip
            command.upgrade(config, "head")
            command.check(config)
            with pytest.raises(RuntimeError, match="cohorts are stored"):
                command.downgrade(config, BEFORE)
            with engine.begin() as conn:
                conn.execute(text("DELETE FROM users"))  # cascades to the cohort
                assert conn.execute(text("SELECT count(*) FROM cohorts")).scalar_one() == 0
            command.downgrade(config, BEFORE)
            assert "cohorts" not in inspect(engine).get_table_names()
            command.upgrade(config, THIS)
            assert "assignment_decks" in inspect(engine).get_table_names()
        finally:
            get_settings.cache_clear()
