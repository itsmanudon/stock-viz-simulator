"""The migration chain upgrades, downgrades and upgrades again (audit OP-15).

Runs the real Alembic chain on an empty scratch PostgreSQL database: up to
head, down past this week's migrations (the Aegis read tables, the fixed
opening value, the job run log), and up again.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from stockviz.settings import get_settings
from tests.pg_scratch import postgres_admin_url, scratch_alembic_engine

pytestmark = pytest.mark.skipif(
    postgres_admin_url() is None,
    reason="DATABASE_URL is not PostgreSQL",
)

API_ROOT = Path(__file__).resolve().parents[1]
BEFORE_THIS_WEEK = "b6e8a20f4c31"


def test_upgrade_downgrade_upgrade(monkeypatch) -> None:
    with scratch_alembic_engine() as engine:
        monkeypatch.setenv("DATABASE_URL", engine.url.render_as_string(hide_password=False))
        get_settings.cache_clear()
        try:
            config = Config(str(API_ROOT / "alembic.ini"))
            config.set_main_option("script_location", str(API_ROOT / "migrations"))

            command.upgrade(config, "head")
            tables = set(inspect(engine).get_table_names())
            assert {"aegis_documents", "job_runs"} <= tables
            assert "opening_nav" in {c["name"] for c in inspect(engine).get_columns("portfolios")}

            command.downgrade(config, BEFORE_THIS_WEEK)
            inspector = inspect(engine)
            assert not {"aegis_documents", "job_runs"} & set(inspector.get_table_names())
            assert "opening_nav" not in {c["name"] for c in inspector.get_columns("portfolios")}

            command.upgrade(config, "head")
            assert {"aegis_documents", "job_runs"} <= set(inspect(engine).get_table_names())
        finally:
            engine.dispose()
            get_settings.cache_clear()


def test_two_upgrades_at_once_both_succeed() -> None:
    """The API start and the cron can migrate together (audit OP-10).

    Two real ``alembic upgrade head`` processes on one empty database: the
    advisory lock in ``migrations/env.py`` makes the second wait and then find
    nothing to do. Without it they both create the first tables and one fails.
    """
    import os
    import subprocess
    import sys

    with scratch_alembic_engine() as engine:
        env = {**os.environ, "DATABASE_URL": engine.url.render_as_string(hide_password=False)}
        command_line = [sys.executable, "-m", "alembic", "upgrade", "head"]
        runs = [
            subprocess.Popen(
                command_line,
                cwd=API_ROOT,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            for _ in range(2)
        ]
        outputs = [run.communicate(timeout=120)[0] for run in runs]
        try:
            assert [run.returncode for run in runs] == [0, 0], outputs
            assert {"aegis_documents", "job_runs"} <= set(inspect(engine).get_table_names())
        finally:
            engine.dispose()
