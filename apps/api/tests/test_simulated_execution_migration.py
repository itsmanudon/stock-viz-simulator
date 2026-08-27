"""PostgreSQL Alembic upgrade/downgrade for simulated_executions."""

from __future__ import annotations

import os
import subprocess
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from tests.pg_scratch import postgres_admin_url, scratch_alembic_engine

pytestmark = pytest.mark.skipif(
    postgres_admin_url() is None,
    reason="DATABASE_URL is not PostgreSQL",
)

API_ROOT = Path(__file__).resolve().parents[1]
PREVIOUS_REVISION = "a8c3e1f4b902"
HEAD_REVISION = "b4e8c2d1a905"


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


def test_simulated_executions_migration_upgrade_downgrade_reupgrade() -> None:
    with scratch_alembic_engine() as engine:
        _alembic(_url(engine), "upgrade", PREVIOUS_REVISION)

        inspector = inspect(engine)
        assert "trades" in inspector.get_table_names()
        assert "simulated_executions" not in inspector.get_table_names()

        with Session(engine) as session:
            session.execute(
                text(
                    "INSERT INTO users (email, name, created_at) "
                    "VALUES ('mig@stockviz.dev', 'Mig', :ts)"
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
                    "INSERT INTO portfolios (user_id, name, cash_balance, created_at) "
                    "VALUES (:uid, 'Default', 100000, :ts)"
                ),
                {"uid": user_id, "ts": datetime(2026, 1, 1)},
            )
            portfolio_id = session.execute(text("SELECT id FROM portfolios")).scalar_one()
            session.execute(
                text(
                    "INSERT INTO trades (portfolio_id, ticker, side, quantity, price, ts) "
                    "VALUES (:pid, 'AAPL', 'BUY', 1, 10, :ts)"
                ),
                {"pid": portfolio_id, "ts": datetime(2026, 1, 2)},
            )
            session.commit()
            trade_id = session.execute(text("SELECT id FROM trades")).scalar_one()

        _alembic(_url(engine), "upgrade", "head")
        inspector = inspect(engine)
        assert "simulated_executions" in inspector.get_table_names()

        with Session(engine) as session:
            remaining = session.execute(
                text("SELECT ticker, price FROM trades WHERE id = :id"), {"id": trade_id}
            ).one()
            assert remaining[0] == "AAPL"
            assert Decimal(str(remaining[1])) == Decimal("10")
            count = session.execute(text("SELECT COUNT(*) FROM simulated_executions")).scalar_one()
            assert count == 0

            session.execute(
                text(
                    "INSERT INTO simulated_executions "
                    "(trade_id, profile_name, model_version, reference_price, fill_price, "
                    "reason, assumptions, market_interval, order_type, evaluated_at, created_at) "
                    "VALUES (:tid, 'legacy_close', 'v1', 10, 10, 'test', "
                    "CAST(:assumptions AS jsonb), '1d', 'market', :ts, :ts)"
                ),
                {
                    "tid": trade_id,
                    "assumptions": '["Uses stored 1d close"]',
                    "ts": datetime(2026, 1, 3),
                },
            )
            session.commit()

            with pytest.raises(IntegrityError):
                session.execute(
                    text(
                        "INSERT INTO simulated_executions "
                        "(trade_id, profile_name, model_version, fill_price, reason, "
                        "assumptions, market_interval, order_type, evaluated_at, created_at) "
                        "VALUES (:tid, 'legacy_close', 'v1', 10, 'dup', "
                        "CAST('[]' AS jsonb), '1d', 'market', :ts, :ts)"
                    ),
                    {"tid": trade_id, "ts": datetime(2026, 1, 4)},
                )
                session.commit()
            session.rollback()

        _alembic(_url(engine), "downgrade", PREVIOUS_REVISION)
        inspector = inspect(engine)
        assert "simulated_executions" not in inspector.get_table_names()
        with Session(engine) as session:
            assert session.execute(text("SELECT COUNT(*) FROM trades")).scalar_one() == 1

        _alembic(_url(engine), "upgrade", HEAD_REVISION)
        inspector = inspect(engine)
        assert "simulated_executions" in inspector.get_table_names()
        with Session(engine) as session:
            assert session.execute(text("SELECT COUNT(*) FROM trades")).scalar_one() == 1
            assert (
                session.execute(text("SELECT COUNT(*) FROM simulated_executions")).scalar_one() == 0
            )
