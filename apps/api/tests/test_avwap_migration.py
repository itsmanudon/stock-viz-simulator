"""A3.3's migration (``b8d4e6f1a3c7``) on PostgreSQL: up, down, up.

The kind check takes ``avwap``; the downgrade deletes avwap rows (older code
cannot read them), keeps the others and refuses ``avwap`` again.
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
BEFORE = "f3bb96a753c6"


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


def test_avwap_kind_migration_up_down_up(monkeypatch) -> None:
    with scratch_alembic_engine() as engine:
        monkeypatch.setenv("DATABASE_URL", engine.url.render_as_string(hide_password=False))
        get_settings.cache_clear()
        try:
            config = Config(str(API_ROOT / "alembic.ini"))
            config.set_main_option("script_location", str(API_ROOT / "migrations"))
            command.upgrade(config, BEFORE)
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
                "INSERT INTO drawings (user_id, instrument_id, kind, points, style, label, "
                "locked, created_at, updated_at) VALUES (:u, :i, :k, :p, '{}', :l, false, "
                "now(), now())"
            )
            hline = {
                "u": uid,
                "i": iid,
                "k": "hline",
                "p": '[{"ts": null, "price": "1"}]',
                "l": None,
            }
            avwap = {"u": uid, "i": iid, "k": "avwap", "p": '[{"ts": "2026-01-05", "price": null}]',
                     "l": "swing"}  # fmt: skip
            with engine.begin() as conn:
                conn.execute(insert, hline)
            with pytest.raises(Exception, match="ck_drawings_kind"), engine.begin() as conn:
                conn.execute(insert, avwap)

            command.upgrade(config, "head")
            with engine.begin() as conn:
                conn.execute(insert, avwap)
                kinds = conn.execute(text("SELECT kind FROM drawings ORDER BY id")).scalars().all()
                assert kinds == ["hline", "avwap"]

            command.downgrade(config, BEFORE)
            with engine.begin() as conn:
                kinds = conn.execute(text("SELECT kind FROM drawings ORDER BY id")).scalars().all()
                assert kinds == ["hline"]
            with pytest.raises(Exception, match="ck_drawings_kind"), engine.begin() as conn:
                conn.execute(insert, avwap)

            command.upgrade(config, "head")
            with engine.begin() as conn:
                conn.execute(insert, avwap)
                assert conn.execute(text("SELECT count(*) FROM drawings")).scalar_one() == 2
            assert "drawings" in set(inspect(engine).get_table_names())
        finally:
            engine.dispose()
            get_settings.cache_clear()
