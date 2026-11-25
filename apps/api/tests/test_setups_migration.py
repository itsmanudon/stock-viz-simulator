"""A2.2's migration (``e6364eff4e51``) on PostgreSQL: up, down, up.

The spine is additive: three new tables and a nullable ``setup_version_id``
on saved screens, alerts and experiment runs. Down removes exactly those.
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
BEFORE = "85e6a9572a9f"
LINKED = ("saved_screens", "alerts", "experiment_runs")


def _state(engine) -> tuple[set[str], dict[str, bool]]:
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    linked = {
        t: "setup_version_id" in {c["name"] for c in inspector.get_columns(t)} for t in LINKED
    }
    return tables, linked


def test_spine_migration_up_down_up(monkeypatch) -> None:
    with scratch_alembic_engine() as engine:
        monkeypatch.setenv("DATABASE_URL", engine.url.render_as_string(hide_password=False))
        get_settings.cache_clear()
        try:
            config = Config(str(API_ROOT / "alembic.ini"))
            config.set_main_option("script_location", str(API_ROOT / "migrations"))
            command.upgrade(config, "head")
            tables, linked = _state(engine)
            assert {"setups", "setup_versions", "theses"} <= tables
            assert all(linked.values())

            # The constraints hold: one rule per setup, presets have no owner.
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO setups (id, name, kind, is_preset, created_at) "
                        "VALUES (1, 'p', 'screen', true, now())"
                    )
                )
                conn.execute(
                    text(
                        "INSERT INTO setup_versions (setup_id, version, rule_text, "
                        "canonical_text, rule_hash, timeframe, created_at) "
                        "VALUES (1, 1, 'close > open', 'close > open', 'h', 'daily', now())"
                    )
                )
            with (
                pytest.raises(Exception, match="uq_setup_versions_setup_rule_hash"),
                engine.begin() as conn,
            ):
                conn.execute(
                    text(
                        "INSERT INTO setup_versions (setup_id, version, rule_text, "
                        "canonical_text, rule_hash, timeframe, created_at) "
                        "VALUES (1, 2, 'x', 'x', 'h', 'daily', now())"
                    )
                )
            with (
                pytest.raises(Exception, match="ck_setups_preset_owner"),
                engine.begin() as conn,
            ):
                conn.execute(
                    text(
                        "INSERT INTO setups (name, kind, is_preset, created_at) "
                        "VALUES ('u', 'screen', false, now())"
                    )
                )

            command.downgrade(config, BEFORE)
            tables, linked = _state(engine)
            assert not {"setups", "setup_versions", "theses"} & tables
            assert not any(linked.values())

            command.upgrade(config, "head")
            tables, linked = _state(engine)
            assert {"setups", "setup_versions", "theses"} <= tables
            assert all(linked.values())
        finally:
            engine.dispose()
            get_settings.cache_clear()
