"""A6.9's migration (``e9a4b6c8d0f3``) on PostgreSQL: up, down, up.

The upgrade adds ``replay_orders.parent_id`` / ``oco_group`` with the
``bracket`` type and the ``pending`` status, and ``replay_sessions.interval``
(default ``1d``) / ``feed``. An existing session reads as daily. The
downgrade refuses while a bracket or an intraday session is stored.
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
BEFORE = "c8d3e5f7a9b2"
THIS = "e9a4b6c8d0f3"


def _order(conn, session_id: int, kind: str, status: str = "open", parent: int | None = None):
    columns = "session_id, ticker, side, order_type, quantity, limit_price, status, placed_at, "
    columns += "created_at, updated_at"
    values = "(:s, 'AAPL', 'buy', :k, 1, 100, :st, now(), now(), now()"
    params: dict[str, object] = {"s": session_id, "k": kind, "st": status}
    if parent is not None:
        columns += ", parent_id"
        values += ", :p"
        params["p"] = parent
    return conn.execute(
        text(f"INSERT INTO replay_orders ({columns}) VALUES {values}) RETURNING id"), params
    ).scalar_one()


def test_a69_migration_up_down_up(monkeypatch) -> None:
    with scratch_alembic_engine() as engine:
        monkeypatch.setenv("DATABASE_URL", engine.url.render_as_string(hide_password=False))
        get_settings.cache_clear()
        try:
            config = Config(str(API_ROOT / "alembic.ini"))
            config.set_main_option("script_location", str(API_ROOT / "migrations"))
            command.upgrade(config, BEFORE)
            with engine.begin() as conn:
                conn.execute(text(
                    "INSERT INTO users (email, name, created_at) VALUES ('m@x.dev', 'M', now())"
                ))  # fmt: skip
                conn.execute(text(
                    "INSERT INTO symbols (ticker, name, is_active, currency, created_at) "
                    "VALUES ('AAPL', 'Apple', true, 'USD', now())"
                ))  # fmt: skip
                iid = conn.execute(text(
                    "SELECT instrument_id FROM instrument_identifiers "
                    "WHERE scheme = 'yahoo' AND value = 'AAPL'"
                )).scalar_one()  # fmt: skip
                sid = conn.execute(
                    text(
                        "INSERT INTO replay_sessions (user_id, ticker, instrument_id, "
                        "profile_name, model_version, start_at, current_at, end_at, "
                        "starting_cash, cash_balance, status, created_at, updated_at) VALUES "
                        "((SELECT id FROM users), 'AAPL', :i, 'legacy_close', 'v1', "
                        "'2024-06-03', '2024-06-03', '2024-06-05', 1000, 1000, 'active', "
                        "now(), now()) RETURNING id"
                    ),
                    {"i": iid},
                ).scalar_one()
                with pytest.raises(Exception, match="ck_replay_orders_type"), conn.begin_nested():
                    _order(conn, sid, "bracket")
            command.upgrade(config, THIS)
            columns = {c["name"] for c in inspect(engine).get_columns("replay_sessions")}
            assert {"interval", "feed"} <= columns
            with engine.begin() as conn:
                assert (
                    conn.execute(text("SELECT interval FROM replay_sessions")).scalar_one() == "1d"
                )
                entry = _order(conn, sid, "bracket")
                child = _order(conn, sid, "stop_loss", "pending", entry)
                conn.execute(text("UPDATE replay_orders SET oco_group = :e"), {"e": entry})
                with pytest.raises(Exception, match="ck_replay_orders_status"), conn.begin_nested():
                    _order(conn, sid, "limit", "waiting")
                # The children go with their entry.
                conn.execute(text("DELETE FROM replay_orders WHERE id = :e"), {"e": entry})
                assert conn.execute(
                    text("SELECT count(*) FROM replay_orders WHERE id = :c"), {"c": child}
                ).scalar_one() == 0  # fmt: skip
                _order(conn, sid, "bracket")
            # The models match the head schema.
            command.upgrade(config, "head")
            command.check(config)
            command.downgrade(config, THIS)
            with pytest.raises(RuntimeError, match="brackets or intraday sessions"):
                command.downgrade(config, BEFORE)
            with engine.begin() as conn:
                conn.execute(text("DELETE FROM replay_orders"))
                conn.execute(text("UPDATE replay_sessions SET interval = '5m', feed = 'file'"))
            with pytest.raises(RuntimeError, match="brackets or intraday sessions"):
                command.downgrade(config, BEFORE)
            with engine.begin() as conn:
                conn.execute(text("UPDATE replay_sessions SET interval = '1d', feed = NULL"))
            command.downgrade(config, BEFORE)
            columns = {c["name"] for c in inspect(engine).get_columns("replay_orders")}
            assert "parent_id" not in columns and "oco_group" not in columns
            command.upgrade(config, THIS)
            columns = {c["name"] for c in inspect(engine).get_columns("replay_orders")}
            assert {"parent_id", "oco_group"} <= columns
        finally:
            get_settings.cache_clear()
