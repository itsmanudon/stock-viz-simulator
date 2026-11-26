"""A4.6's migration (``a6c4e2f8b913``) on PostgreSQL: up, down, up.

``replay_sessions`` gains currency / fee schedule / lag override (existing
rows read USD, none, false), ``replay_fills`` gains fees (0) and the order
link, and ``replay_orders`` and ``replay_drawings`` arrive with their checks
and cascades; the downgrade removes them all.
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
BEFORE = "e5a7c9b1d324"


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


def _cols(engine, table: str) -> set[str]:
    return {c["name"] for c in inspect(engine).get_columns(table)}


def test_a46_replay_migration_up_down_up(monkeypatch) -> None:
    with scratch_alembic_engine() as engine:
        monkeypatch.setenv("DATABASE_URL", engine.url.render_as_string(hide_password=False))
        get_settings.cache_clear()
        try:
            config = Config(str(API_ROOT / "alembic.ini"))
            config.set_main_option("script_location", str(API_ROOT / "migrations"))
            command.upgrade(config, BEFORE)
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
                conn.execute(
                    text(
                        "INSERT INTO replay_fills (session_id, ticker, side, quantity, "
                        "fill_price, profile_name, model_version, reason, assumptions, "
                        "market_interval, order_type, evaluated_at, created_at) VALUES (:s, "
                        "'AAPL', 'buy', 1, 10, 'legacy_close', 'v1', 'r', '[]', '1d', "
                        "'market', now(), now())"
                    ),
                    {"s": sid},
                )
            command.upgrade(config, "head")
            assert {"currency", "fee_schedule", "lag_override"} <= _cols(engine, "replay_sessions")
            assert {"fees", "fee_lines", "order_id"} <= _cols(engine, "replay_fills")
            tables = set(inspect(engine).get_table_names())
            assert {"replay_orders", "replay_drawings"} <= tables
            with engine.begin() as conn:
                row = conn.execute(
                    text("SELECT currency, fee_schedule, lag_override FROM replay_sessions")
                ).one()
                assert tuple(row) == ("USD", "none", False)
                assert conn.execute(text("SELECT fees FROM replay_fills")).scalar_one() == 0
                oid = conn.execute(
                    text(
                        "INSERT INTO replay_orders (session_id, ticker, side, order_type, "
                        "quantity, limit_price, status, placed_at, created_at, updated_at) "
                        "VALUES (:s, 'AAPL', 'buy', 'limit', 1, 9, 'open', now(), now(), now()) "
                        "RETURNING id"
                    ),
                    {"s": sid},
                ).scalar_one()
                conn.execute(text("UPDATE replay_fills SET order_id = :o"), {"o": oid})
                conn.execute(
                    text(
                        "INSERT INTO replay_drawings (session_id, kind, points, style, locked, "
                        "created_at, updated_at) VALUES (:s, 'hline', "
                        '\'[{"ts": null, "price": "1"}]\', \'{}\', false, now(), now())'
                    ),
                    {"s": sid},
                )
            with pytest.raises(Exception, match="ck_replay_orders_type"), engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO replay_orders (session_id, ticker, side, order_type, "
                        "quantity, limit_price, status, placed_at, created_at, updated_at) "
                        "VALUES (:s, 'AAPL', 'buy', 'market', 1, 9, 'open', now(), now(), now())"
                    ),
                    {"s": sid},
                )
            with engine.begin() as conn:
                conn.execute(text("DELETE FROM replay_orders"))
                assert conn.execute(text("SELECT order_id FROM replay_fills")).scalar_one() is None
                conn.execute(text("DELETE FROM replay_sessions"))
                assert conn.execute(text("SELECT count(*) FROM replay_drawings")).scalar_one() == 0

            command.downgrade(config, BEFORE)
            tables = set(inspect(engine).get_table_names())
            assert "replay_orders" not in tables and "replay_drawings" not in tables
            assert "currency" not in _cols(engine, "replay_sessions")
            assert "fees" not in _cols(engine, "replay_fills")
            command.upgrade(config, "head")
            assert {"replay_orders", "replay_drawings"} <= set(inspect(engine).get_table_names())
        finally:
            engine.dispose()
            get_settings.cache_clear()
