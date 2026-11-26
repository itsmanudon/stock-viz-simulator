"""A3.2's migration (``f3bb96a753c6``) on PostgreSQL: up, down, up.

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
BEFORE = "5a167f08f3f7"


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


def test_drawings_migration_up_down_up(monkeypatch) -> None:
    with scratch_alembic_engine() as engine:
        monkeypatch.setenv("DATABASE_URL", engine.url.render_as_string(hide_password=False))
        get_settings.cache_clear()
        try:
            config = Config(str(API_ROOT / "alembic.ini"))
            config.set_main_option("script_location", str(API_ROOT / "migrations"))
            command.upgrade(config, BEFORE)
            assert "drawings" not in set(inspect(engine).get_table_names())
            command.upgrade(config, "head")
            assert "drawings" in set(inspect(engine).get_table_names())
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
                iid = conn.execute(
                    text("SELECT instrument_id FROM instrument_identifiers WHERE value = 'AAPL'")
                ).scalar_one()
                insert = text(
                    "INSERT INTO drawings (user_id, instrument_id, kind, points, style, locked, "
                    "created_at, updated_at) VALUES (:u, :i, :k, "
                    '\'[{"ts": null, "price": "1"}]\', \'{}\', false, now(), now())'
                )
                conn.execute(insert, {"u": uid, "i": iid, "k": "hline"})
            with pytest.raises(Exception, match="ck_drawings_kind"), engine.begin() as conn:
                conn.execute(insert, {"u": uid, "i": iid, "k": "arrow"})
            with engine.begin() as conn:
                conn.execute(text("DELETE FROM users WHERE id = :u"), {"u": uid})
                assert conn.execute(text("SELECT count(*) FROM drawings")).scalar_one() == 0

            command.downgrade(config, BEFORE)
            assert "drawings" not in set(inspect(engine).get_table_names())
            command.upgrade(config, "head")
            assert "drawings" in set(inspect(engine).get_table_names())
        finally:
            engine.dispose()
            get_settings.cache_clear()
