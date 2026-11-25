"""A2.3's migration (``6e6c8aed50fb``) on PostgreSQL: up, down, up.

Additive: ``screen_runs``, ``notification_channels``, ``delivery_attempts``,
``saved_screens.notify_on_change``, ``notifications.data`` and the check
that a ``rule`` alert names a setup version. Down removes exactly those
(and any ``rule`` alerts, which the older code cannot read).
"""

from __future__ import annotations

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
BEFORE = "e6364eff4e51"
TABLES = {"screen_runs", "notification_channels", "delivery_attempts"}


def _state(engine) -> tuple[set[str], bool, bool]:
    inspector = inspect(engine)
    tables = set(inspector.get_table_names()) & TABLES
    notify = "notify_on_change" in {c["name"] for c in inspector.get_columns("saved_screens")}
    data = "data" in {c["name"] for c in inspector.get_columns("notifications")}
    return tables, notify, data


def test_delivery_migration_up_down_up(monkeypatch) -> None:
    with scratch_alembic_engine() as engine:
        monkeypatch.setenv("DATABASE_URL", engine.url.render_as_string(hide_password=False))
        get_settings.cache_clear()
        try:
            config = Config(str(API_ROOT / "alembic.ini"))
            config.set_main_option("script_location", str(API_ROOT / "migrations"))
            command.upgrade(config, "head")
            assert _state(engine) == (TABLES, True, True)

            with engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO users (id, email, name, created_at) "
                        "VALUES (1, 'm@stockviz.dev', 'm', now())"
                    )
                )
                conn.execute(
                    text(
                        "INSERT INTO symbols (ticker, name, is_active, currency, created_at) VALUES ('AAPL', 'Apple', true, 'USD', now())"
                    )
                )
            # A rule alert without a version is refused.
            with (
                pytest.raises(Exception, match="ck_alerts_rule_has_version"),
                engine.begin() as conn,
            ):
                conn.execute(
                    text(
                        "INSERT INTO alerts (user_id, ticker, kind, repeat, cooldown_sessions, "
                        "paused, created_at) VALUES (1, 'AAPL', 'rule', 'once', 1, false, now())"
                    )
                )
            # One channel row per user and channel.
            insert_channel = text(
                "INSERT INTO notification_channels (user_id, channel, enabled, config, "
                "muted_categories, created_at, updated_at) "
                "VALUES (1, 'webhook', false, '{}', '[]', now(), now())"
            )
            with engine.begin() as conn:
                conn.execute(insert_channel)
            with (
                pytest.raises(Exception, match="uq_notification_channels_user_channel"),
                engine.begin() as conn,
            ):
                conn.execute(insert_channel)
            with engine.begin() as conn:
                default = conn.execute(
                    text(
                        "SELECT column_default FROM information_schema.columns "
                        "WHERE table_name = 'saved_screens' AND column_name = 'notify_on_change'"
                    )
                ).scalar_one()
            assert "false" in str(default)

            command.downgrade(config, BEFORE)
            assert _state(engine) == (set(), False, False)

            command.upgrade(config, "head")
            assert _state(engine) == (TABLES, True, True)
        finally:
            engine.dispose()
            get_settings.cache_clear()
