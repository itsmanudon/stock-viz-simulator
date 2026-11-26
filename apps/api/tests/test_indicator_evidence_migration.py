"""A3.4 migration (``d89bb4083e68``) on PostgreSQL: up, down, up.

The ``drawings`` table arrives with its kind check and cascades from users
and instruments; the downgrade drops it.
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
BEFORE = "b8d4e6f1a3c7"


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


def test_indicator_evidence_migration_up_down_up(monkeypatch) -> None:
    with scratch_alembic_engine() as engine:
        monkeypatch.setenv("DATABASE_URL", engine.url.render_as_string(hide_password=False))
        get_settings.cache_clear()
        try:
            config = Config(str(API_ROOT / "alembic.ini"))
            config.set_main_option("script_location", str(API_ROOT / "migrations"))
            command.upgrade(config, BEFORE)
            assert "indicator_evidence" not in set(inspect(engine).get_table_names())
            command.upgrade(config, "head")
            assert "indicator_evidence" in set(inspect(engine).get_table_names())
            insert = text(
                "INSERT INTO indicator_evidence (indicator, rule, rule_hash, universe, "
                "point_in_time, survivorship_biased, window_start, window_end, horizon, "
                "symbols, n_events, overlapping_skipped, grade, computed_at) VALUES "
                "('rsi', 'rsi(14) crosses_above 30', 'h1', 'pinned', false, true, "
                "'2016-01-01', '2026-01-01', 20, 3, 40, 0, 'C', now())"
            )
            with engine.begin() as conn:
                conn.execute(insert)
            with (
                pytest.raises(Exception, match="uq_indicator_evidence_rule_window"),
                engine.begin() as conn,
            ):
                conn.execute(insert)
            command.downgrade(config, BEFORE)
            assert "indicator_evidence" not in set(inspect(engine).get_table_names())
            command.upgrade(config, "head")
            assert "indicator_evidence" in set(inspect(engine).get_table_names())
        finally:
            engine.dispose()
            get_settings.cache_clear()
