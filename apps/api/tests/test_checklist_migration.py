"""A2.4's migration (``65fc5117cbf1``) on PostgreSQL: up, down, up.

Adds ``checklist_scores`` and ``checklist_evidence``; moves ``recommendations``
to the ``archive`` schema with its rows (its keys to live tables and its
instrument trigger dropped). Down moves it back with its keys and trigger and
drops the two tables.
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
BEFORE = "6e6c8aed50fb"
NEW = {"checklist_scores", "checklist_evidence"}


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


def _state(engine) -> tuple[set[str], bool, bool]:
    inspector = inspect(engine)
    public = set(inspector.get_table_names())
    archived = "recommendations" in set(inspector.get_table_names(schema="archive"))
    return public & (NEW | {"recommendations"}), archived, "recommendations" in public


def _keys_and_trigger(conn, schema: str) -> tuple[set[str], set[str]]:
    keys = set(
        conn.execute(
            text(
                "SELECT conname FROM pg_constraint WHERE conrelid = CAST(:t AS regclass) AND contype = 'f'"
            ),
            {"t": f"{schema}.recommendations"},
        ).scalars()
    )
    triggers = set(
        conn.execute(
            text(
                "SELECT tgname FROM pg_trigger WHERE tgrelid = CAST(:t AS regclass) AND NOT tgisinternal"
            ),
            {"t": f"{schema}.recommendations"},
        ).scalars()
    )
    return keys, triggers


def test_checklist_migration_up_down_up(monkeypatch) -> None:
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
                conn.execute(
                    text(
                        "INSERT INTO recommendations (ticker, score, computed_at) "
                        "VALUES ('AAPL', 5, now())"
                    )
                )

            command.upgrade(config, "head")
            assert _state(engine) == (NEW, True, False)
            with engine.begin() as conn:
                # The rows are kept, and the archive holds no key to a live table.
                assert conn.execute(
                    text("SELECT ticker, score FROM archive.recommendations")
                ).all() == [("AAPL", 5)]
                assert _keys_and_trigger(conn, "archive") == (set(), set())
                # A symbol can go even though an archived row names it.
                conn.execute(text("DELETE FROM instrument_identifiers"))
                conn.execute(text("DELETE FROM instruments"))
                conn.execute(text("DELETE FROM symbols"))
                conn.execute(
                    text(
                        "INSERT INTO symbols (ticker, name, is_active, currency, created_at) "
                        "VALUES ('MSFT', 'Microsoft', true, 'USD', now())"
                    )
                )
                instrument = conn.execute(
                    text("SELECT instrument_id FROM instrument_identifiers WHERE value = 'MSFT'")
                ).scalar_one()
                conn.execute(
                    text(
                        "INSERT INTO checklist_scores (instrument_id, session_date, dimensions, "
                        "met_count, evaluated_count, computed_at) "
                        "VALUES (:i, '2026-11-25', '[]', 0, 0, now())"
                    ),
                    {"i": instrument},
                )
            with (
                pytest.raises(Exception, match="uq_checklist_scores_instrument_session"),
                engine.begin() as conn,
            ):
                conn.execute(
                    text(
                        "INSERT INTO checklist_scores (instrument_id, session_date, dimensions, "
                        "met_count, evaluated_count, computed_at) "
                        "VALUES (:i, '2026-11-25', '[]', 0, 0, now())"
                    ),
                    {"i": instrument},
                )

            command.downgrade(config, BEFORE)
            assert _state(engine) == ({"recommendations"}, False, True)
            with engine.begin() as conn:
                assert conn.execute(text("SELECT count(*) FROM recommendations")).scalar_one() == 1
                keys, triggers = _keys_and_trigger(conn, "public")
                assert keys == {"recommendations_ticker_fkey", "fk_recommendations_instrument_id"}
                assert triggers == {"trg_recommendations_instrument_id"}
                # The restored trigger fills the instrument of a new row.
                conn.execute(
                    text(
                        "INSERT INTO recommendations (ticker, score, computed_at) "
                        "VALUES ('MSFT', 3, now())"
                    )
                )
                assert (
                    conn.execute(
                        text("SELECT instrument_id FROM recommendations WHERE ticker = 'MSFT'")
                    ).scalar_one()
                    == instrument
                )

            command.upgrade(config, "head")
            assert _state(engine) == (NEW, True, False)
        finally:
            engine.dispose()
            get_settings.cache_clear()
