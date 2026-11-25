"""A3.5 migration (``bb2ee29c23d3``) on PostgreSQL: up, down, up.

``symbol_metrics`` gains the four return columns; the downgrade drops them
and keeps the rows.
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
BEFORE = "d89bb4083e68"
COLUMNS = {"return_1m", "return_3m", "return_6m", "return_12m"}


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


def _columns(engine) -> set[str]:
    return {c["name"] for c in inspect(engine).get_columns("symbol_metrics")}


def test_symbol_metrics_returns_migration_up_down_up(monkeypatch) -> None:
    with scratch_alembic_engine() as engine:
        monkeypatch.setenv("DATABASE_URL", engine.url.render_as_string(hide_password=False))
        get_settings.cache_clear()
        try:
            config = Config(str(API_ROOT / "alembic.ini"))
            config.set_main_option("script_location", str(API_ROOT / "migrations"))
            command.upgrade(config, "head")
            assert _columns(engine) >= COLUMNS
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO symbols (ticker, name, currency, is_active, created_at) "
                        "VALUES ('AAPL', 'Apple', 'USD', true, now())"
                    )
                )
                conn.execute(
                    text(
                        "INSERT INTO symbol_metrics (ticker, instrument_id, return_3m, "
                        "sentiment_article_count, computed_at) SELECT 'AAPL', instrument_id, "
                        "12.5, 0, now() FROM instrument_identifiers WHERE value = 'AAPL' LIMIT 1"
                    )
                )
            command.downgrade(config, BEFORE)
            assert not (COLUMNS & _columns(engine))
            with engine.connect() as conn:
                assert conn.execute(text("SELECT count(*) FROM symbol_metrics")).scalar() == 1
            command.upgrade(config, "head")
            assert _columns(engine) >= COLUMNS
        finally:
            engine.dispose()
            get_settings.cache_clear()
