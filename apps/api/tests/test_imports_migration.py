"""A5.3's migration (``e3a1c5d7f902``) on PostgreSQL: up, down, up.

The upgrade adds ``import_batches``, ``broker_fills`` and
``trades.broker_fill_id``. With a broker fill stored the downgrade refuses
and changes nothing; without one it drops the three, and the upgrade runs
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
BEFORE = "b5d4a7e1c902"
THIS = "e3a1c5d7f902"


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


def test_a53_imports_migration_up_down_up(monkeypatch) -> None:
    with scratch_alembic_engine() as engine:
        monkeypatch.setenv("DATABASE_URL", engine.url.render_as_string(hide_password=False))
        get_settings.cache_clear()
        try:
            config = Config(str(API_ROOT / "alembic.ini"))
            config.set_main_option("script_location", str(API_ROOT / "migrations"))
            command.upgrade(config, BEFORE)
            assert "broker_fills" not in inspect(engine).get_table_names()
            command.upgrade(config, THIS)
            tables = set(inspect(engine).get_table_names())
            assert {"import_batches", "broker_fills"} <= tables
            trade_cols = {c["name"] for c in inspect(engine).get_columns("trades")}
            assert "broker_fill_id" in trade_cols
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
                        "VALUES ('a@x.dev', false, now()) RETURNING id"
                    )
                ).scalar_one()
                pid = conn.execute(
                    text(
                        "INSERT INTO portfolios (user_id, name, kind, is_default, cash_tracked, "
                        "broker, cash_balance, base_currency, opening_nav, created_at) VALUES "
                        "(:u, 'Z', 'imported', false, false, 'zerodha', 0, 'INR', 0, now()) "
                        "RETURNING id"
                    ),
                    {"u": uid},
                ).scalar_one()
                iid = conn.execute(
                    text("SELECT instrument_id FROM instrument_identifiers WHERE value='TCS.NS'")
                ).scalar_one()
                batch = conn.execute(
                    text(
                        "INSERT INTO import_batches (portfolio_id, broker, column_map, "
                        "file_sha256, rows_total, rows_added, rows_duplicate, rows_unmatched, "
                        "rows_skipped_segment, rows_rejected, created_at) VALUES "
                        "(:p, 'zerodha', 'zerodha_tradebook_v1', repeat('a', 64), 1, 1, 0, 0, "
                        "0, 0, now()) RETURNING id"
                    ),
                    {"p": pid},
                ).scalar_one()
                params = {"p": pid, "b": batch, "i": iid}
                fill_sql = (
                    "INSERT INTO broker_fills (portfolio_id, import_batch_id, kind, broker, "
                    "exchange, trade_id, instrument_id, ticker, side, quantity, price, "
                    "executed_at, created_at) VALUES (:p, :b, 'trade', 'zerodha', 'NSE', 'T1', "
                    ":i, 'TCS.NS', 'buy', 1, 100, now(), now())"
                )
                conn.execute(text(fill_sql), params)
                # The dedupe key.
            with pytest.raises(Exception, match="uq_broker_fills_trade"), engine.begin() as conn:
                conn.execute(text(fill_sql), params)
            with pytest.raises(Exception, match="broker fill"):
                command.downgrade(config, BEFORE)
            assert "broker_fills" in inspect(engine).get_table_names()
            with engine.begin() as conn:
                conn.execute(text("DELETE FROM broker_fills"))
            command.downgrade(config, BEFORE)
            tables = set(inspect(engine).get_table_names())
            assert "broker_fills" not in tables and "import_batches" not in tables
            trade_cols = {c["name"] for c in inspect(engine).get_columns("trades")}
            assert "broker_fill_id" not in trade_cols
            command.upgrade(config, "head")
            assert "broker_fills" in inspect(engine).get_table_names()
        finally:
            engine.dispose()
            get_settings.cache_clear()
