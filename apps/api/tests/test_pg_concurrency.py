"""PostgreSQL-only proof that two sessions cannot over-reserve or over-spend cash.

SQLite accepts ``FOR UPDATE`` but does not enforce it, so the rest of the
suite cannot demonstrate concurrent exclusion. These tests skip *only* when
``DATABASE_URL`` is unset or is not Postgres. Auth failures, DDL failures,
deadlocks, and assertion failures fail the run.
"""

from __future__ import annotations

import threading
from datetime import datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlmodel import Session

from stockviz.models import Portfolio, PriceBar, Symbol, TradeSide, User
from stockviz.models.order import OrderType
from stockviz.services.trading import (
    DEFAULT_STARTING_CASH,
    InsufficientCash,
    create_pending_order,
    ensure_default_portfolio,
    execute_trade,
)
from stockviz.services.trading.buying_power import available_cash, lock_portfolio, reserved_cash
from stockviz.services.trading.execute import MICROS
from tests.pg_scratch import postgres_admin_url, scratch_postgres_engine

pytestmark = pytest.mark.skipif(
    postgres_admin_url() is None,
    reason="DATABASE_URL is not PostgreSQL",
)


def _user(session: Session, suffix: str) -> int:
    user = User(email=f"{suffix}-{uuid4().hex}@stockviz.dev", name=suffix)
    session.add(user)
    session.commit()
    session.refresh(user)
    assert user.id is not None
    return user.id


def _usd_symbol(session: Session, ticker: str, *, close: Decimal) -> None:
    session.add(Symbol(ticker=ticker, name=f"{ticker} Inc.", currency="USD"))
    session.commit()
    session.add(
        PriceBar(
            ticker=ticker,
            ts=datetime(2025, 4, 10),
            interval="1d",
            open=close,
            high=close,
            low=close,
            close=close,
            volume=1_000,
            source="test",
        )
    )
    session.commit()


def test_two_sessions_cannot_overcommit_pending_buy_reservations() -> None:
    with scratch_postgres_engine() as engine:
        with Session(engine) as setup:
            user_id = _user(setup, "lock")
            setup.add(Symbol(ticker="AAPL", name="Apple", currency="USD"))
            setup.commit()
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
            assert row.cash_balance == DEFAULT_STARTING_CASH.quantize(MICROS)


def test_second_session_sees_committed_cash_after_for_update() -> None:
    """A blocked locker must observe the winner's committed ``cash_balance``.

    Session A takes ``FOR UPDATE`` first, then fills a 70k market buy.
    Session B starts ``execute_trade`` only after A holds the lock, so it
    waits, then must reject a 50k buy against the remaining 30k — not the
    stale 100k identity-map value.
    """
    with scratch_postgres_engine() as engine:
        with Session(engine) as setup:
            user_id = _user(setup, "stale")
            _usd_symbol(setup, "MSFT", close=Decimal("100"))
            portfolio = ensure_default_portfolio(setup, user_id)
            assert portfolio.id is not None
            portfolio_id = portfolio.id

        a_locked = threading.Event()
        outcomes: dict[str, str] = {}

        def worker_a() -> None:
            with Session(engine) as session:
                lock_portfolio(session, portfolio_id)
                a_locked.set()
                try:
                    execute_trade(
                        session,
                        user_id=user_id,
                        ticker="MSFT",
                        side=TradeSide.BUY,
                        quantity=Decimal("700"),
                    )
                    outcomes["a"] = "ok"
                except InsufficientCash:
                    outcomes["a"] = "reject"
                except Exception as exc:
                    outcomes["a"] = f"error:{type(exc).__name__}:{exc}"

        def worker_b() -> None:
            if not a_locked.wait(timeout=15):
                outcomes["b"] = "error:TimeoutError:A never locked"
                return
            with Session(engine) as session:
                try:
                    execute_trade(
                        session,
                        user_id=user_id,
                        ticker="MSFT",
                        side=TradeSide.BUY,
                        quantity=Decimal("500"),
                    )
                    outcomes["b"] = "ok"
                except InsufficientCash:
                    outcomes["b"] = "reject"
                except Exception as exc:
                    outcomes["b"] = f"error:{type(exc).__name__}:{exc}"

        threads = [
            threading.Thread(target=worker_a),
            threading.Thread(target=worker_b),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
            assert not thread.is_alive()

        assert outcomes.get("a") == "ok", outcomes
        assert outcomes.get("b") == "reject", outcomes

        with Session(engine) as check:
            row = check.get(Portfolio, portfolio_id)
            assert row is not None
            assert row.cash_balance == Decimal("30000").quantize(MICROS)
            assert available_cash(check, row) == Decimal("30000").quantize(MICROS)
