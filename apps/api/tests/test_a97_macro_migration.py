"""A9.7's migration (``f1a9c7e3b5d2``) on PostgreSQL: up, down, up."""

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
BEFORE = "e9a4b6c8d0f3"
THIS = "f1a9c7e3b5d2"


def test_a97_migration_up_down_up(monkeypatch) -> None:
    with scratch_alembic_engine() as engine:
        monkeypatch.setenv("DATABASE_URL", engine.url.render_as_string(hide_password=False))
        get_settings.cache_clear()
        try:
            config = Config(str(API_ROOT / "alembic.ini"))
            config.set_main_option("script_location", str(API_ROOT / "migrations"))
            command.upgrade(config, THIS)
            with engine.begin() as conn:
                conn.execute(text(
                    "INSERT INTO macro_observations (series_id, obs_date, value) "
                    "VALUES ('DGS10', '2026-01-02', 4.1), ('DGS10', '2026-01-05', NULL)"
                ))  # fmt: skip
            command.upgrade(config, "head")
            command.check(config)
            command.downgrade(config, BEFORE)
            names = inspect(engine).get_table_names()
            assert "macro_series" not in names and "macro_observations" not in names
            command.upgrade(config, THIS)
            assert "macro_observations" in inspect(engine).get_table_names()
        finally:
            get_settings.cache_clear()
