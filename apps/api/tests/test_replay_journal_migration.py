"""PostgreSQL Alembic upgrade/downgrade for replay_journals (SIM-07)."""

from __future__ import annotations

import os
import subprocess
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import inspect, text
from sqlmodel import Session

from tests.pg_scratch import postgres_admin_url, scratch_alembic_engine

pytestmark = pytest.mark.skipif(
    postgres_admin_url() is None,
    reason="DATABASE_URL is not PostgreSQL",
)

API_ROOT = Path(__file__).resolve().parents[1]
PREVIOUS_REVISION = "c8e5f1a2b3c4"
HEAD_REVISION = "d6a1b2c3e017"


def _url(engine) -> str:
    return engine.url.render_as_string(hide_password=False)


def _alembic(url: str, *args: str) -> None:
    env = os.environ.copy()
    env["DATABASE_URL"] = url
    subprocess.run(
        ["uv", "run", "alembic", *args],
        check=True,
        cwd=API_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )


def test_replay_journals_migration_upgrade_downgrade_reupgrade() -> None:
    with scratch_alembic_engine() as engine:
        _alembic(_url(engine), "upgrade", PREVIOUS_REVISION)
        inspector = inspect(engine)
        assert "replay_sessions" in inspector.get_table_names()
        assert "replay_journals" not in inspector.get_table_names()

        _alembic(_url(engine), "upgrade", "head")
        inspector = inspect(engine)
        assert "replay_journals" in inspector.get_table_names()
        columns = {col["name"] for col in inspector.get_columns("replay_journals")}
        assert {
            "session_id",
            "thesis",
            "invalidation",
            "expected_holding_bars",
            "confidence",
            "reflection",
            "locked_at",
        } <= columns

        with Session(engine) as session:
            session.execute(
                text(
                    "INSERT INTO users (email, name, created_at) "
                    "VALUES ('journal-mig@stockviz.dev', 'Mig', :ts)"
                ),
                {"ts": datetime(2026, 1, 1)},
            )
            user_id = session.execute(text("SELECT id FROM users")).scalar_one()
            session.execute(
                text(
                    "INSERT INTO symbols (ticker, name, currency, is_active, created_at) "
                    "VALUES ('AAPL', 'Apple', 'USD', true, :ts)"
                ),
                {"ts": datetime(2026, 1, 1)},
            )
            session.execute(
                text(
                    "INSERT INTO replay_sessions "
                    "(user_id, ticker, profile_name, model_version, start_at, current_at, "
                    "end_at, starting_cash, cash_balance, status, created_at, updated_at) "
                    "VALUES (:uid, 'AAPL', 'legacy_close', 'v1', :ts, :ts, :ts, "
                    "100000, 100000, 'active', :ts, :ts)"
                ),
                {"uid": user_id, "ts": datetime(2024, 6, 3, 0, 0, 0)},
            )
            session.commit()
            session_id = session.execute(text("SELECT id FROM replay_sessions")).scalar_one()
            session.execute(
                text(
                    "INSERT INTO replay_journals "
                    "(session_id, thesis, confidence, created_at, updated_at) "
                    "VALUES (:sid, 'Hold', 3, :ts, :ts)"
                ),
                {"sid": session_id, "ts": datetime(2024, 6, 3, 0, 0, 0)},
            )
            session.commit()
            assert session.execute(text("SELECT COUNT(*) FROM replay_journals")).scalar_one() == 1

        _alembic(_url(engine), "downgrade", PREVIOUS_REVISION)
        inspector = inspect(engine)
        assert "replay_journals" not in inspector.get_table_names()
        assert "replay_sessions" in inspector.get_table_names()

        _alembic(_url(engine), "upgrade", HEAD_REVISION)
        inspector = inspect(engine)
        assert "replay_journals" in inspector.get_table_names()
        with Session(engine) as session:
            assert session.execute(text("SELECT COUNT(*) FROM replay_journals")).scalar_one() == 0
            assert session.execute(text("SELECT COUNT(*) FROM replay_sessions")).scalar_one() == 1
