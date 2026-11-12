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
from sqlmodel import Session, select

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


def test_two_sessions_with_one_client_order_id_fill_once() -> None:
    """Two concurrent repeats of one market order: one fill, one cash debit (#67)."""
    with scratch_postgres_engine() as engine:
        with Session(engine) as setup:
            user_id = _user(setup, "key")
            _usd_symbol(setup, "AAPL", close=Decimal("100"))
            portfolio = ensure_default_portfolio(setup, user_id)
            assert portfolio.id is not None
            portfolio_id = portfolio.id

        barrier = threading.Barrier(2, timeout=15)
        trade_ids: list[object] = []
        lock = threading.Lock()

        def worker() -> None:
            with Session(engine) as session:
                barrier.wait()
                try:
                    result: object = execute_trade(
                        session,
                        user_id=user_id,
                        ticker="AAPL",
                        side=TradeSide.BUY,
                        quantity=Decimal("10"),
                        client_order_id="same-ticket",
                    ).trade.id
                except Exception as exc:
                    result = f"error:{type(exc).__name__}:{exc}"
                with lock:
                    trade_ids.append(result)

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=20)
            assert not thread.is_alive()

        assert len(trade_ids) == 2 and trade_ids[0] == trade_ids[1], trade_ids
        with Session(engine) as check:
            row = check.get(Portfolio, portfolio_id)
            assert row is not None
            assert row.cash_balance == (DEFAULT_STARTING_CASH - Decimal("1000")).quantize(MICROS)


# ---------------------------------------------------------------------------
# One test per competing writer (audit LG-11): each pair races on one
# portfolio and the ledger must come out as if they had run one after another.
# ---------------------------------------------------------------------------


def _race(engine, *jobs) -> list[str]:
    """Run each job in its own session at once; return "ok" or the error name."""
    barrier = threading.Barrier(len(jobs), timeout=15)
    outcomes: list[str] = []
    lock = threading.Lock()

    def run(job) -> None:
        with Session(engine) as session:
            barrier.wait()
            try:
                job(session)
                result = "ok"
            except Exception as exc:
                result = type(exc).__name__
            with lock:
                outcomes.append(result)

    threads = [threading.Thread(target=run, args=(job,)) for job in jobs]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)
        assert not thread.is_alive()
    return sorted(outcomes)


def _holding(session: Session, user_id: int, ticker: str, quantity: str) -> int:
    from stockviz.models import Position

    portfolio = ensure_default_portfolio(session, user_id)
    assert portfolio.id is not None
    session.add(
        Position(
            portfolio_id=portfolio.id,
            ticker=ticker,
            quantity=Decimal(quantity),
            avg_cost=Decimal(1),
        )
    )
    session.commit()
    return portfolio.id


def test_two_concurrent_sells_cannot_sell_more_than_is_held() -> None:
    from stockviz.models import Position
    from stockviz.services.trading import InsufficientPosition

    with scratch_postgres_engine() as engine:
        with Session(engine) as setup:
            user_id = _user(setup, "sells")
            _usd_symbol(setup, "AAPL", close=Decimal("100"))
            portfolio_id = _holding(setup, user_id, "AAPL", "100")

        def sell(session: Session) -> None:
            execute_trade(
                session, user_id=user_id, ticker="AAPL", side=TradeSide.SELL, quantity=Decimal(60)
            )

        assert _race(engine, sell, sell) == sorted(["ok", InsufficientPosition.__name__])
        with Session(engine) as check:
            position = check.exec(
                select(Position).where(Position.portfolio_id == portfolio_id)
            ).one()
            assert position.quantity == Decimal(40)
            row = check.get(Portfolio, portfolio_id)
            assert row is not None
            assert row.cash_balance == (DEFAULT_STARTING_CASH + Decimal(6000)).quantize(MICROS)


def test_two_concurrent_closes_of_one_option_pay_once() -> None:
    from datetime import timedelta

    from stockviz._time import utcnow
    from stockviz.models.option import OptionsPosition, OptionStatus, OptionType
    from stockviz.services.options import OptionTradeError, close_option

    with scratch_postgres_engine() as engine:
        with Session(engine) as setup:
            user_id = _user(setup, "close")
            setup.add(Symbol(ticker="AAPL", name="Apple", currency="USD"))
            setup.commit()
            for day in range(40):
                price = Decimal(100 + (day % 5))
                setup.add(
                    PriceBar(
                        ticker="AAPL",
                        ts=datetime(2026, 9, 1) + timedelta(days=day),
                        interval="1d",
                        open=price,
                        high=price,
                        low=price,
                        close=price,
                        volume=1_000,
                        source="test",
                    )
                )
            portfolio = ensure_default_portfolio(setup, user_id)
            assert portfolio.id is not None
            portfolio_id = portfolio.id
            option = OptionsPosition(
                user_id=user_id,
                portfolio_id=portfolio_id,
                ticker="AAPL",
                option_type=OptionType.CALL,
                strike=Decimal(100),
                expiry=utcnow().date() + timedelta(days=60),
                quantity=1,
                premium_paid=Decimal("500"),
                status=OptionStatus.OPEN,
            )
            setup.add(option)
            setup.commit()
            assert option.id is not None
            option_id = option.id

        def close_it(session: Session) -> None:
            close_option(session, user_id=user_id, option_id=option_id)

        assert _race(engine, close_it, close_it) == sorted(["ok", OptionTradeError.__name__])
        with Session(engine) as check:
            closed = check.get(OptionsPosition, option_id)
            assert closed is not None and closed.proceeds is not None
            row = check.get(Portfolio, portfolio_id)
            assert row is not None
            assert row.cash_balance == (DEFAULT_STARTING_CASH + closed.proceeds).quantize(MICROS)


def test_cancel_racing_settlement_leaves_one_outcome() -> None:
    from sqlmodel import select as sql_select

    from stockviz.models import Trade
    from stockviz.models.order import OrderStatus, PendingOrder
    from stockviz.services.trading import cancel_pending_order, settle_pending_orders

    with scratch_postgres_engine() as engine:
        with Session(engine) as setup:
            user_id = _user(setup, "cancel")
            _usd_symbol(setup, "AAPL", close=Decimal("100"))
            order = create_pending_order(
                setup,
                user_id=user_id,
                ticker="AAPL",
                side=TradeSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal(10),
                limit_price=Decimal(110),  # triggers at the 100 close
            )
            assert order.id is not None
            order_id, portfolio_id = order.id, order.portfolio_id

        def cancel(session: Session) -> None:
            cancel_pending_order(session, user_id=user_id, order_id=order_id)

        def settle(session: Session) -> None:
            settle_pending_orders(session)

        _race(engine, cancel, settle)
        with Session(engine) as check:
            final = check.get(PendingOrder, order_id)
            assert final is not None
            trades = check.exec(sql_select(Trade).where(Trade.portfolio_id == portfolio_id)).all()
            row = check.get(Portfolio, portfolio_id)
            assert row is not None
            if final.status == OrderStatus.FILLED:
                assert len(trades) == 1
                assert row.cash_balance == (DEFAULT_STARTING_CASH - Decimal(1000)).quantize(MICROS)
            else:
                assert final.status == OrderStatus.CANCELLED
                assert trades == []
                assert row.cash_balance == DEFAULT_STARTING_CASH.quantize(MICROS)


def test_two_concurrent_dividend_runs_credit_once() -> None:
    from datetime import date

    from sqlmodel import select as sql_select

    from stockviz.models.dividend import Dividend, PortfolioDividend
    from stockviz.services.trading import credit_due_dividends

    with scratch_postgres_engine() as engine:
        with Session(engine) as setup:
            user_id = _user(setup, "dividend")
            _usd_symbol(setup, "AAPL", close=Decimal("100"))
            portfolio_id = _holding(setup, user_id, "AAPL", "10")
            portfolio = setup.get(Portfolio, portfolio_id)
            assert portfolio is not None
            portfolio.created_at = datetime(2026, 1, 1)
            setup.add(portfolio)
            setup.add(Dividend(ticker="AAPL", ex_date=date(2026, 3, 9), amount=Decimal("0.5")))
            setup.commit()

        def credit(session: Session) -> None:
            credit_due_dividends(session, credit_date=date(2026, 3, 9))

        assert _race(engine, credit, credit) == ["ok", "ok"]
        with Session(engine) as check:
            credits = check.exec(
                sql_select(PortfolioDividend).where(PortfolioDividend.portfolio_id == portfolio_id)
            ).all()
            assert len(credits) == 1
            row = check.get(Portfolio, portfolio_id)
            assert row is not None
            assert row.cash_balance == (DEFAULT_STARTING_CASH + Decimal(5)).quantize(MICROS)


def test_the_database_refuses_a_second_row_for_one_holding() -> None:
    from sqlalchemy.exc import IntegrityError

    from stockviz.models import Position

    with scratch_postgres_engine() as engine, Session(engine) as session:
        user_id = _user(session, "dup")
        _usd_symbol(session, "AAPL", close=Decimal("100"))
        portfolio_id = _holding(session, user_id, "AAPL", "1")
        session.add(
            Position(
                portfolio_id=portfolio_id, ticker="AAPL", quantity=Decimal(1), avg_cost=Decimal(1)
            )
        )
        with pytest.raises(IntegrityError, match="uq_positions_portfolio_ticker"):
            session.commit()
        session.rollback()
        row = session.get(Portfolio, portfolio_id)
        assert row is not None
        row.cash_balance = Decimal(-1)
        session.add(row)
        with pytest.raises(IntegrityError, match="ck_portfolios_cash_nonnegative"):
            session.commit()
