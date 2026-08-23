"""PostgreSQL-only proof that two sessions cannot over-reserve cash.

SQLite accepts ``FOR UPDATE`` but does not enforce it, so the rest of the
suite cannot demonstrate concurrent exclusion. CI sets ``DATABASE_URL`` to
Postgres; locally the test is skipped unless that env var is a Postgres URL.

The test creates a throwaway database so ``create_all`` cannot leave tables
in the app database that would then break ``alembic upgrade`` (CI runs
pytest *before* migrations).
"""

from __future__ import annotations

import os
import threading
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.engine.url import make_url
from sqlmodel import Session, SQLModel, create_engine, text

import stockviz.models  # noqa: F401 — register metadata
from stockviz.models import Portfolio, Symbol, TradeSide, User
from stockviz.models.order import OrderType
from stockviz.services.trading import (
    InsufficientCash,
    create_pending_order,
    ensure_default_portfolio,
)
from stockviz.services.trading.buying_power import available_cash, reserved_cash


def _postgres_url() -> str | None:
    raw = os.environ.get("DATABASE_URL", "")
    if not raw:
        return None
    if raw.startswith("postgres://"):
        raw = "postgresql+psycopg://" + raw[len("postgres://") :]
    elif raw.startswith("postgresql://"):
        raw = "postgresql+psycopg://" + raw[len("postgresql://") :]
    if "postgresql" not in raw:
        return None
    return raw


def _scratch_engine(admin_url: str):
    dbname = "stockviz_lock_test"
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(
            text(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = :d AND pid <> pg_backend_pid()"
            ),
            {"d": dbname},
        )
        conn.execute(text(f"DROP DATABASE IF EXISTS {dbname}"))
        conn.execute(text(f"CREATE DATABASE {dbname}"))
    test_url = make_url(admin_url).set(database=dbname)
    engine = create_engine(str(test_url), pool_pre_ping=True)
    SQLModel.metadata.create_all(engine)
    return admin, engine, dbname


def _drop_scratch(admin, engine, dbname: str) -> None:
    engine.dispose()
    with admin.connect() as conn:
        conn.execute(
            text(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = :d AND pid <> pg_backend_pid()"
            ),
            {"d": dbname},
        )
        conn.execute(text(f"DROP DATABASE IF EXISTS {dbname}"))
    admin.dispose()


@pytest.mark.skipif(_postgres_url() is None, reason="DATABASE_URL is not PostgreSQL")
def test_two_sessions_cannot_overcommit_pending_buy_reservations() -> None:
    admin_url = _postgres_url()
    assert admin_url is not None
    try:
        admin, engine, dbname = _scratch_engine(admin_url)
    except Exception as exc:
        pytest.skip(f"could not create scratch Postgres database: {exc}")

    try:
        with Session(engine) as setup:
            user = User(email=f"lock-{uuid4().hex}@stockviz.dev", name="Lock")
            setup.add(user)
            setup.add(Symbol(ticker="AAPL", name="Apple", currency="USD"))
            setup.commit()
            setup.refresh(user)
            assert user.id is not None
            user_id = user.id
            portfolio = ensure_default_portfolio(setup, user_id)
            assert portfolio.id is not None
            portfolio_id = portfolio.id

        barrier = threading.Barrier(2, timeout=15)
        outcomes: list[str] = []
        lock = threading.Lock()

        def worker() -> None:
            with Session(engine) as session:
                barrier.wait()
                try:
                    create_pending_order(
                        session,
                        user_id=user_id,
                        ticker="AAPL",
                        side=TradeSide.BUY,
                        order_type=OrderType.LIMIT,
                        quantity=Decimal("800"),
                        limit_price=Decimal("100"),
                    )
                    result = "ok"
                except InsufficientCash:
                    result = "reject"
                except Exception as exc:
                    result = f"error:{type(exc).__name__}:{exc}"
                with lock:
                    outcomes.append(result)

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=20)
            assert not thread.is_alive()

        assert sorted(outcomes) == ["ok", "reject"], outcomes

        with Session(engine) as check:
            row = check.get(Portfolio, portfolio_id)
            assert row is not None
            assert reserved_cash(check, portfolio_id) == Decimal("80000.000000")
            assert available_cash(check, row) == Decimal("20000.000000")
            assert row.cash_balance == Decimal("100000.00")
    finally:
        _drop_scratch(admin, engine, dbname)
