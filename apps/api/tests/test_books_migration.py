"""A5.1's migration (``6ad74b7c4b5b``) on PostgreSQL: up, down, up, with rows.

Two users with one portfolio each before the upgrade. After it: both are
default paper books, snapshots carry their book, the old split application
is kept as the user's row beside a new book row. One user then holds three
books: the downgrade refuses and changes nothing. With the extra books gone
the downgrade restores one row per (action, user) and the old unique keys,
and the upgrade runs again.
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
BEFORE = "53b66a2e2ec2"
THIS = "6ad74b7c4b5b"


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


def test_a51_books_migration_up_down_up(monkeypatch) -> None:
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
                a, b = (
                    conn.execute(
                        text(
                            "INSERT INTO users (email, public_profile, created_at) "
                            "VALUES (:e, false, now()) RETURNING id"
                        ),
                        {"e": email},
                    ).scalar_one()
                    for email in ("a@x.dev", "b@x.dev")
                )
                pa, pb = (
                    conn.execute(
                        text(
                            "INSERT INTO portfolios (user_id, name, cash_balance, base_currency, "
                            "opening_nav, created_at) VALUES (:u, 'Default', :c, :ccy, :c, "
                            "now()) RETURNING id"
                        ),
                        {"u": uid, "c": cash, "ccy": ccy},
                    ).scalar_one()
                    for uid, cash, ccy in ((a, 100000, "USD"), (b, 10000000, "INR"))
                )
                for uid, day in ((a, "2026-11-20"), (a, "2026-11-21"), (b, "2026-11-21")):
                    conn.execute(
                        text(
                            "INSERT INTO portfolio_snapshots (user_id, date, nav) "
                            "VALUES (:u, :d, 1)"
                        ),
                        {"u": uid, "d": day},
                    )
                action = conn.execute(
                    text(
                        "INSERT INTO corporate_actions (ticker, kind, ex_date, ratio_from, "
                        "ratio_to, source, recorded_at) VALUES ('AAPL', 'split', '2020-08-31', "
                        "1, 4, 'test', now()) RETURNING id"
                    )
                ).scalar_one()
                conn.execute(
                    text(
                        "INSERT INTO corporate_action_applications (action_id, user_id, "
                        "applied_at, summary) VALUES (:a, :u, now(), '1 order(s)')"
                    ),
                    {"a": action, "u": a},
                )

            command.upgrade(config, THIS)
            assert {
                "kind",
                "is_default",
                "cash_tracked",
                "holder_kind",
                "holder_label",
                "broker",
                "archived_at",
            } <= _columns(engine, "portfolios")
            with engine.begin() as conn:
                books = conn.execute(
                    text(
                        "SELECT id, kind, is_default, cash_tracked, holder_kind, archived_at "
                        "FROM portfolios ORDER BY id"
                    )
                ).all()
                assert [tuple(r) for r in books] == [
                    (pa, "paper", True, True, "self", None),
                    (pb, "paper", True, True, "self", None),
                ]
                snaps = conn.execute(
                    text("SELECT user_id, portfolio_id FROM portfolio_snapshots ORDER BY id")
                ).all()
                assert [tuple(r) for r in snaps] == [(a, pa), (a, pa), (b, pb)]
                apps = conn.execute(
                    text(
                        "SELECT user_id, portfolio_id, summary FROM "
                        "corporate_action_applications ORDER BY portfolio_id NULLS FIRST"
                    )
                ).all()
                assert [tuple(r) for r in apps] == [(a, None, "1 order(s)"), (a, pa, "1 order(s)")]
                # User a takes two more books; b stays with one.
                conn.execute(
                    text(
                        "INSERT INTO portfolios (user_id, name, kind, is_default, cash_tracked, "
                        "cash_balance, base_currency, opening_nav, created_at) VALUES "
                        "(:u, 'Family', 'paper', false, true, 100000, 'USD', 100000, now()), "
                        "(:u, 'Zerodha', 'imported', false, false, 0, 'INR', 0, now())"
                    ),
                    {"u": a},
                )
            # Constraints hold: one default per user, a unique name, no PAN-free kinds.
            for bad, name in (
                (
                    "INSERT INTO portfolios (user_id, name, is_default, cash_balance, opening_nav, "
                    "created_at) VALUES (:u, 'Two', true, 1, 1, now())",
                    "uq_portfolios_user_default",
                ),
                (
                    "INSERT INTO portfolios (user_id, name, cash_balance, opening_nav, created_at) "
                    "VALUES (:u, 'Family', 1, 1, now())",
                    "uq_portfolios_user_name",
                ),
                ("UPDATE portfolios SET kind = 'live' WHERE user_id = :u", "ck_portfolios_kind"),
                (
                    "UPDATE portfolios SET archived_at = now() WHERE user_id = :u AND is_default",
                    "ck_portfolios_default_not_archived",
                ),
            ):
                with pytest.raises(Exception, match=name), engine.begin() as conn:
                    conn.execute(text(bad), {"u": a})
            with (
                pytest.raises(Exception, match="uq_portfolio_snapshots_portfolio_date"),
                engine.begin() as conn,
            ):
                conn.execute(
                    text(
                        "INSERT INTO portfolio_snapshots (user_id, portfolio_id, date, nav) "
                        "VALUES (:u, :p, '2026-11-20', 2)"
                    ),
                    {"u": a, "p": pa},
                )

            with pytest.raises(RuntimeError, match="1 user\\(s\\) hold more than one book"):
                command.downgrade(config, BEFORE)
            with engine.begin() as conn:
                assert (
                    conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
                    == THIS
                )
                assert conn.execute(text("SELECT count(*) FROM portfolios")).scalar_one() == 4
                conn.execute(text("DELETE FROM portfolios WHERE NOT is_default"))

            command.downgrade(config, BEFORE)
            assert "is_default" not in _columns(engine, "portfolios")
            assert "portfolio_id" not in _columns(engine, "portfolio_snapshots")
            assert "portfolio_id" not in _columns(engine, "corporate_action_applications")
            assert "portfolio_id" not in _columns(engine, "alerts")
            with engine.begin() as conn:
                apps = conn.execute(
                    text("SELECT action_id, user_id FROM corporate_action_applications")
                ).all()
                assert [tuple(r) for r in apps] == [(action, a)]
                assert (
                    conn.execute(text("SELECT count(*) FROM portfolio_snapshots")).scalar_one() == 3
                )
            with pytest.raises(Exception, match="ix_portfolios_user_id"), engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO portfolios (user_id, name, cash_balance, opening_nav, "
                        "created_at) VALUES (:u, 'Again', 1, 1, now())"
                    ),
                    {"u": a},
                )

            command.upgrade(config, "head")
            with engine.begin() as conn:
                assert (
                    conn.execute(
                        text("SELECT count(*) FROM portfolios WHERE is_default")
                    ).scalar_one()
                    == 2
                )
                assert (
                    conn.execute(
                        text("SELECT count(*) FROM corporate_action_applications")
                    ).scalar_one()
                    == 2
                )
        finally:
            engine.dispose()
            get_settings.cache_clear()
