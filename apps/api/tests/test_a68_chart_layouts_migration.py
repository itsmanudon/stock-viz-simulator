"""A6.8's migration (``d4a8f6c2b1e9``) on PostgreSQL: up, down, up.

The upgrade adds ``chart_templates`` and ``chart_layouts`` with their check
constraints and per-user unique names; the downgrade drops both.
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
THIS = "d4a8f6c2b1e9"
TABLES = {"chart_templates", "chart_layouts"}


def test_a68_migration_up_down_up(monkeypatch) -> None:
    with scratch_alembic_engine() as engine:
        monkeypatch.setenv("DATABASE_URL", engine.url.render_as_string(hide_password=False))
        get_settings.cache_clear()
        try:
            config = Config(str(API_ROOT / "alembic.ini"))
            config.set_main_option("script_location", str(API_ROOT / "migrations"))
            command.upgrade(config, BEFORE)
            assert not TABLES & set(inspect(engine).get_table_names())
            command.upgrade(config, THIS)
            assert set(inspect(engine).get_table_names()) >= TABLES
            with engine.begin() as conn:
                uid = conn.execute(text(
                    "INSERT INTO users (email, public_profile, created_at) "
                    "VALUES ('m@x.dev', false, now()) RETURNING id"
                )).scalar_one()  # fmt: skip
                conn.execute(
                    text(
                        "INSERT INTO chart_templates (user_id, name, chart_type, scale, "
                        "indicators, pane_heights, created_at, updated_at) VALUES "
                        "(:u, 'T', 'line', 'log', '[\"sma_20\"]', '{\"price\": 300}', now(), "
                        "now())"
                    ),
                    {"u": uid},
                )
                with (
                    pytest.raises(Exception, match="ck_chart_templates_chart_type"),
                    conn.begin_nested(),
                ):
                    conn.execute(text("UPDATE chart_templates SET chart_type = 'renko'"))
                with (
                    pytest.raises(Exception, match="ck_chart_templates_scale"),
                    conn.begin_nested(),
                ):
                    conn.execute(text("UPDATE chart_templates SET scale = 'sqrt'"))
                conn.execute(
                    text(
                        "INSERT INTO chart_layouts (user_id, name, grid, panes, created_at, "
                        "updated_at) VALUES (:u, 'L', '4', '[]', now(), now())"
                    ),
                    {"u": uid},
                )
                with pytest.raises(Exception, match="ck_chart_layouts_grid"), conn.begin_nested():
                    conn.execute(text("UPDATE chart_layouts SET grid = '3'"))
                with (
                    pytest.raises(Exception, match="uq_chart_layouts_user_name"),
                    conn.begin_nested(),
                ):
                    conn.execute(
                        text(
                            "INSERT INTO chart_layouts (user_id, name, grid, panes, "
                            "created_at, updated_at) VALUES (:u, 'L', '1', '[]', now(), now())"
                        ),
                        {"u": uid},
                    )
            # The models match the head schema (check at head and come back).
            command.upgrade(config, "head")
            command.check(config)
            command.downgrade(config, BEFORE)
            assert not TABLES & set(inspect(engine).get_table_names())
            command.upgrade(config, THIS)
            assert set(inspect(engine).get_table_names()) >= TABLES
        finally:
            get_settings.cache_clear()
