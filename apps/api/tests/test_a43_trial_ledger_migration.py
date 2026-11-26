"""A4.3 migration (``e5a7c9b1d324``) on PostgreSQL: up, down, up.

``backtest_trials`` and ``holdout_unlocks`` are created; the downgrade drops
both and leaves every other table as it was.
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
BEFORE = "c4f2a8e91b07"
TABLES = {"backtest_trials", "holdout_unlocks"}


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


def _tables(engine) -> set[str]:
    return set(inspect(engine).get_table_names())


def test_trial_ledger_migration_up_down_up(monkeypatch) -> None:
    with scratch_alembic_engine() as engine:
        monkeypatch.setenv("DATABASE_URL", engine.url.render_as_string(hide_password=False))
        get_settings.cache_clear()
        try:
            config = Config(str(API_ROOT / "alembic.ini"))
            config.set_main_option("script_location", str(API_ROOT / "migrations"))
            command.upgrade(config, "head")
            assert _tables(engine) >= TABLES
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO backtest_trials (user_id, mode, source, family_key, "
                        "family_label, strategy_hash, data_fingerprint, label, observations, "
                        "sharpe, total_return, created_at, last_run_at) VALUES (NULL, "
                        "'template', 'run', 'k', 'x', 'h', 'f', 'l', 10, 0.1, 0.0, now(), now())"
                    )
                )
                runs = conn.execute(text("SELECT runs FROM backtest_trials")).scalar()
                assert runs == 1  # the server default
            command.downgrade(config, BEFORE)
            assert not (TABLES & _tables(engine))
            assert "experiment_runs" in _tables(engine)
            command.upgrade(config, "head")
            assert _tables(engine) >= TABLES
        finally:
            engine.dispose()
            get_settings.cache_clear()
