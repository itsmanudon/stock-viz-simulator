"""A7.14's migration (``b7e2f4a6c8d1``) on PostgreSQL: up, down, up."""

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
BEFORE = "a7d1c3e5f9b2"
THIS = "b7e2f4a6c8d1"


def test_a714_migration_up_down_up(monkeypatch) -> None:
    with scratch_alembic_engine() as engine:
        monkeypatch.setenv("DATABASE_URL", engine.url.render_as_string(hide_password=False))
        get_settings.cache_clear()
        try:
            config = Config(str(API_ROOT / "alembic.ini"))
            config.set_main_option("script_location", str(API_ROOT / "migrations"))
            command.upgrade(config, THIS)
            with engine.begin() as conn:
                conn.execute(text(
                    "INSERT INTO fo_daily (underlying, series, day, option_type, strike_offset, close, "
                    "iv, oi, volume, spot, last_minute, minutes) VALUES ('NIFTY', 'weekly', "
                    "'2024-07-23', 'CE', 0, 120, 14.0, 1000, 30, 24000, '15:29:00', 2)"
                ))  # fmt: skip
            command.upgrade(config, "head")
            command.check(config)
            command.downgrade(config, BEFORE)
            names = inspect(engine).get_table_names()
            assert "fo_daily" not in names and "fo_files" not in names
            command.upgrade(config, THIS)
            assert "fo_daily" in inspect(engine).get_table_names()
        finally:
            get_settings.cache_clear()
