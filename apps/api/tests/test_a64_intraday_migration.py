"""A6.4's migration (``b7c2d4e6f8a1``) on PostgreSQL: up, down, up.

The upgrade adds ``setup_versions.feed`` with checks on it and ``timeframe``,
widens the version key to ``(setup_id, rule_hash, timeframe, feed)``, and
adds the per-bar alert state (``alerts.last_bar_at``, ``last_fired_bar_at``,
``alert_events.bar_at``, ``feed``). The downgrade refuses while an intraday
version exists, then restores the old key.
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
BEFORE = "a6b1c3d5e7f9"
THIS = "b7c2d4e6f8a1"


def _version(conn, setup_id: int, version: int, timeframe: str, feed: str | None = None) -> None:
    cols = "setup_id, version, rule_text, canonical_text, rule_hash, timeframe, created_at"
    vals = ":s, :v, 'close > 1', 'close > 1', 'h', :tf, now()"
    if feed is not None:
        cols, vals = cols + ", feed", vals + ", :feed"
    conn.execute(
        text(f"INSERT INTO setup_versions ({cols}) VALUES ({vals})"),
        {"s": setup_id, "v": version, "tf": timeframe, "feed": feed},
    )


def test_a64_migration_up_down_up(monkeypatch) -> None:
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
                uid = conn.execute(text("SELECT id FROM users")).scalar_one()
                conn.execute(text(
                    "INSERT INTO setups (user_id, name, kind, is_preset, created_at) "
                    "VALUES (:u, 'S', 'alert', false, now())"
                ), {"u": uid})  # fmt: skip
                sid = conn.execute(text("SELECT id FROM setups")).scalar_one()
                _version(conn, sid, 1, "daily")
            command.upgrade(config, THIS)
            cols = {c["name"] for c in inspect(engine).get_columns("setup_versions")}
            assert "feed" in cols
            assert {"last_bar_at", "last_fired_bar_at"} <= {
                c["name"] for c in inspect(engine).get_columns("alerts")
            }
            assert {"bar_at", "feed"} <= {
                c["name"] for c in inspect(engine).get_columns("alert_events")
            }
            with engine.begin() as conn:
                assert conn.execute(text("SELECT feed FROM setup_versions")).scalar_one() == "auto"
                # The same rule hash on 5m bars is another version now.
                _version(conn, sid, 2, "5m", "file")
                with (
                    pytest.raises(Exception, match="ck_setup_versions_timeframe"),
                    conn.begin_nested(),
                ):
                    _version(conn, sid, 3, "2h")
                with (
                    pytest.raises(Exception, match="uq_setup_versions_setup_rule_hash"),
                    conn.begin_nested(),
                ):
                    _version(conn, sid, 4, "5m", "file")
            command.check(config)
            with pytest.raises(RuntimeError, match="intraday setup version"):
                command.downgrade(config, BEFORE)
            with engine.begin() as conn:
                conn.execute(text("DELETE FROM setup_versions WHERE timeframe <> 'daily'"))
            command.downgrade(config, BEFORE)
            assert "feed" not in {c["name"] for c in inspect(engine).get_columns("setup_versions")}
            command.upgrade(config, THIS)
            assert "feed" in {c["name"] for c in inspect(engine).get_columns("setup_versions")}
        finally:
            get_settings.cache_clear()
