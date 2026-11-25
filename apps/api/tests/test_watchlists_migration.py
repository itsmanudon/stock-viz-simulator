"""A2.5's migration (``5a167f08f3f7``) on PostgreSQL: up, down, up.

Existing lists and items are kept; each user's oldest list becomes the
default, lists are numbered by id, and a repeated name gets " (2)". The
partial unique index allows one default per user; the downgrade drops the
new columns, keys and ``column_sets``.
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
BEFORE = "65fc5117cbf1"
NEW_LIST_COLUMNS = {"colour", "position", "is_default", "column_set_id"}


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


def _columns(engine, table: str) -> set[str]:
    return {c["name"] for c in inspect(engine).get_columns(table)}


def test_watchlists_migration_up_down_up(monkeypatch) -> None:
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
                for email in ("a@x.dev", "b@x.dev"):
                    conn.execute(
                        text(
                            "INSERT INTO users (email, public_profile, created_at) "
                            "VALUES (:e, false, now())"
                        ),
                        {"e": email},
                    )
                a, b = conn.execute(text("SELECT id FROM users ORDER BY id")).scalars().all()
                # Two "Default" lists for a (a race the old code allowed), one for b.
                for user in (a, a, b):
                    conn.execute(
                        text(
                            "INSERT INTO watchlists (user_id, name, created_at) "
                            "VALUES (:u, 'Default', now())"
                        ),
                        {"u": user},
                    )
                first = conn.execute(
                    text("SELECT min(id) FROM watchlists WHERE user_id = :u"), {"u": a}
                ).scalar_one()
                conn.execute(
                    text(
                        "INSERT INTO watchlist_items (watchlist_id, ticker, added_at) "
                        "VALUES (:w, 'AAPL', now())"
                    ),
                    {"w": first},
                )

            command.upgrade(config, "head")
            assert "column_sets" in set(inspect(engine).get_table_names())
            assert _columns(engine, "watchlists") >= NEW_LIST_COLUMNS
            assert {"note", "tags"} <= _columns(engine, "watchlist_items")
            with engine.begin() as conn:
                rows = conn.execute(
                    text(
                        "SELECT user_id, name, position, is_default, colour FROM watchlists "
                        "ORDER BY user_id, id"
                    )
                ).all()
                assert rows == [
                    (a, "Default", 0, True, "aqua"),
                    (a, "Default (2)", 1, False, "aqua"),
                    (b, "Default", 0, True, "aqua"),
                ]
                item = conn.execute(
                    text("SELECT watchlist_id, note, tags FROM watchlist_items")
                ).one()
                assert item == (first, None, [])
            # One default per user, names unique per user.
            with (
                pytest.raises(Exception, match="uq_watchlists_user_default"),
                engine.begin() as conn,
            ):
                conn.execute(
                    text(
                        "INSERT INTO watchlists (user_id, name, is_default, created_at) "
                        "VALUES (:u, 'Second', true, now())"
                    ),
                    {"u": a},
                )
            with pytest.raises(Exception, match="uq_watchlists_user_name"), engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO watchlists (user_id, name, created_at) VALUES (:u, 'Default', now())"
                    ),
                    {"u": b},
                )
            # Deleting a column set clears the lists that used it.
            with engine.begin() as conn:
                set_id = conn.execute(
                    text(
                        "INSERT INTO column_sets (user_id, name, columns, created_at, updated_at) "
                        "VALUES (:u, 'Momentum', '[\"rsi_14\"]', now(), now()) RETURNING id"
                    ),
                    {"u": a},
                ).scalar_one()
                conn.execute(
                    text("UPDATE watchlists SET column_set_id = :s WHERE id = :w"),
                    {"s": set_id, "w": first},
                )
                conn.execute(text("DELETE FROM column_sets"))
                assert (
                    conn.execute(
                        text("SELECT column_set_id FROM watchlists WHERE id = :w"), {"w": first}
                    ).scalar_one()
                    is None
                )

            command.downgrade(config, BEFORE)
            assert "column_sets" not in set(inspect(engine).get_table_names())
            assert not NEW_LIST_COLUMNS & _columns(engine, "watchlists")
            assert not {"note", "tags"} & _columns(engine, "watchlist_items")
            with engine.begin() as conn:
                assert conn.execute(text("SELECT count(*) FROM watchlists")).scalar_one() == 3
                assert conn.execute(text("SELECT count(*) FROM watchlist_items")).scalar_one() == 1

            command.upgrade(config, "head")
            assert _columns(engine, "watchlists") >= NEW_LIST_COLUMNS
        finally:
            engine.dispose()
            get_settings.cache_clear()
