"""A6.11's migration (``d1a6b11c2e40``) on PostgreSQL: up, down, up.

The upgrade lets books and import batches name the new brokers and adds
``import_column_maps``. The downgrade refuses while a book names one.
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
BEFORE = "d4a7f9b1c3e5"
THIS = "d1a6b11c2e40"


def _book(conn, broker: str) -> None:
    conn.execute(
        text(
            "INSERT INTO portfolios (user_id, name, kind, is_default, cash_tracked, broker, "
            "holder_kind, cash_balance, base_currency, opening_nav, created_at) VALUES "
            "(1, :n, 'imported', false, false, :b, 'self', 0, 'INR', 0, now())"
        ),
        {"n": f"Book {broker}", "b": broker},
    )


def test_a611_migration_up_down_up(monkeypatch) -> None:
    with scratch_alembic_engine() as engine:
        monkeypatch.setenv("DATABASE_URL", engine.url.render_as_string(hide_password=False))
        get_settings.cache_clear()
        try:
            config = Config(str(API_ROOT / "alembic.ini"))
            config.set_main_option("script_location", str(API_ROOT / "migrations"))
            command.upgrade(config, BEFORE)
            with engine.begin() as conn:
                conn.execute(text(
                    "INSERT INTO users (id, email, name, created_at) "
                    "VALUES (1, 'maps@stockviz.dev', 'Maps', now())"
                ))  # fmt: skip
                with pytest.raises(Exception, match="ck_portfolios_broker"), conn.begin_nested():
                    _book(conn, "dhan")
            command.upgrade(config, THIS)
            assert "import_column_maps" in inspect(engine).get_table_names()
            with engine.begin() as conn:
                _book(conn, "dhan")
                with pytest.raises(Exception, match="ck_portfolios_broker"), conn.begin_nested():
                    _book(conn, "robinhood")
                conn.execute(text(
                    "INSERT INTO import_column_maps (user_id, name, mapping, date_order, "
                    "created_at, updated_at) VALUES (1, 'Mine', '{\"symbol\": \"Ticker\"}', "
                    "'auto', now(), now())"
                ))  # fmt: skip
                with (
                    pytest.raises(Exception, match="ck_import_column_maps_date_order"),
                    conn.begin_nested(),
                ):
                    conn.execute(text("UPDATE import_column_maps SET date_order = 'guess'"))
            command.upgrade(config, "head")
            command.check(config)
            command.downgrade(config, THIS)
            with pytest.raises(RuntimeError, match="other than zerodha"):
                command.downgrade(config, BEFORE)
            with engine.begin() as conn:
                conn.execute(text("DELETE FROM portfolios WHERE broker = 'dhan'"))
            command.downgrade(config, BEFORE)
            assert "import_column_maps" not in inspect(engine).get_table_names()
            command.upgrade(config, THIS)
            assert "import_column_maps" in inspect(engine).get_table_names()
        finally:
            get_settings.cache_clear()
