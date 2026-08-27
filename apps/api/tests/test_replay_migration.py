"""PostgreSQL Alembic upgrade/downgrade for replay_sessions (SIM-05)."""

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
PREVIOUS_REVISION = "b4e8c2d1a905"
HEAD_REVISION = "c5f9d3e2b016"


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


def test_replay_sessions_migration_upgrade_downgrade_reupgrade() -> None:
    with scratch_alembic_engine() as engine:
        _alembic(_url(engine), "upgrade", PREVIOUS_REVISION)

        inspector = inspect(engine)
        assert "simulated_executions" in inspector.get_table_names()
        assert "replay_sessions" not in inspector.get_table_names()
        assert "replay_fills" not in inspector.get_table_names()

        with Session(engine) as session:
            session.execute(
                text(
                    "INSERT INTO users (email, name, created_at) "
                    "VALUES ('replay-mig@stockviz.dev', 'Mig', :ts)"
                ),
                {"ts": datetime(2026, 1, 1)},
            )
            user_id = session.execute(text("SELECT id FROM users")).scalar_one()
            session.commit()

        _alembic(_url(engine), "upgrade", "head")
        inspector = inspect(engine)
        names = inspector.get_table_names()
        assert "replay_sessions" in names
        assert "replay_positions" in names
        assert "replay_fills" in names

        with Session(engine) as session:
            remaining = session.execute(
                text("SELECT email FROM users WHERE id = :id"), {"id": user_id}
            ).one()
            assert remaining[0] == "replay-mig@stockviz.dev"

            session.execute(
                text(
                    "INSERT INTO replay_sessions "
                    "(user_id, profile_name, model_version, clock_now, starting_cash, "
                    "cash_balance, status, created_at, updated_at) "
                    "VALUES (:uid, 'legacy_close', 'v1', :ts, 100000, 100000, 'open', :ts, :ts)"
                ),
                {"uid": user_id, "ts": datetime(2024, 6, 3, 21, 0, 0)},
            )
            session.commit()
            session_id = session.execute(text("SELECT id FROM replay_sessions")).scalar_one()
            session.execute(
                text(
                    "INSERT INTO replay_fills "
                    "(session_id, ticker, side, quantity, fill_price, profile_name, "
                    "model_version, reason, assumptions, market_interval, order_type, "
                    "evaluated_at, created_at) "
                    "VALUES (:sid, 'AAPL', 'buy', 1, 10, 'legacy_close', 'v1', 'test', "
                    "CAST(:assumptions AS jsonb), '1d', 'market', :ts, :ts)"
                ),
                {
                    "sid": session_id,
                    "assumptions": '["Uses stored 1d close"]',
                    "ts": datetime(2024, 6, 3, 21, 0, 0),
                },
            )
            session.commit()
            assert session.execute(text("SELECT COUNT(*) FROM replay_fills")).scalar_one() == 1
            assert (
                session.execute(text("SELECT COUNT(*) FROM simulated_executions")).scalar_one() == 0
            )

        _alembic(_url(engine), "downgrade", PREVIOUS_REVISION)
        inspector = inspect(engine)
        assert "replay_sessions" not in inspector.get_table_names()
        assert "replay_fills" not in inspector.get_table_names()
        assert "simulated_executions" in inspector.get_table_names()
        with Session(engine) as session:
            assert session.execute(text("SELECT COUNT(*) FROM users")).scalar_one() == 1

        _alembic(_url(engine), "upgrade", HEAD_REVISION)
        inspector = inspect(engine)
        assert "replay_sessions" in inspector.get_table_names()
        with Session(engine) as session:
            assert session.execute(text("SELECT COUNT(*) FROM replay_sessions")).scalar_one() == 0
            assert session.execute(text("SELECT COUNT(*) FROM users")).scalar_one() == 1
