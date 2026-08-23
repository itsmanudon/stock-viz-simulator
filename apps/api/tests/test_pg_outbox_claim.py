"""PostgreSQL proof that two publishers cannot claim the same outbox row."""

from __future__ import annotations

import threading
import time
from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlmodel import Session

from stockviz.events.outbox import claim_unpublished
from stockviz.models import OutboxEvent, PriceBar, Symbol, TradeSide, User
from stockviz.services.trading import ensure_default_portfolio, execute_trade
from tests.pg_scratch import postgres_admin_url, scratch_postgres_engine

pytestmark = pytest.mark.skipif(
    postgres_admin_url() is None,
    reason="DATABASE_URL is not PostgreSQL",
)


def test_two_sessions_cannot_claim_the_same_unpublished_row() -> None:
    with scratch_postgres_engine() as engine:
        with Session(engine) as setup:
            user = User(email=f"claim-{uuid4().hex}@stockviz.dev", name="Claim")
            setup.add(user)
            setup.commit()
            setup.refresh(user)
            assert user.id is not None
            setup.add(Symbol(ticker="AAPL", name="Apple", currency="USD"))
            setup.commit()
            setup.add(
                PriceBar(
                    ticker="AAPL",
                    ts=datetime(2025, 4, 10),
                    interval="1d",
                    open=Decimal("10"),
                    high=Decimal("10"),
                    low=Decimal("10"),
                    close=Decimal("10"),
                    volume=1_000,
                    source="test",
                )
            )
            setup.commit()
            ensure_default_portfolio(setup, user.id)
            execute_trade(
                setup,
                user_id=user.id,
                ticker="AAPL",
                side=TradeSide.BUY,
                quantity=Decimal("1"),
            )

        first_claimed = threading.Event()
        claimed: dict[str, list[str]] = {}

        def worker_a() -> None:
            with Session(engine) as session:
                rows = claim_unpublished(session, limit=10)
                claimed["a"] = [str(row.id) for row in rows]
                first_claimed.set()
                time.sleep(0.5)
                session.rollback()

        def worker_b() -> None:
            if not first_claimed.wait(timeout=15):
                claimed["b"] = []
                return
            with Session(engine) as session:
                rows = claim_unpublished(session, limit=10)
                claimed["b"] = [str(row.id) for row in rows]
                session.rollback()

        threads = [threading.Thread(target=worker_a), threading.Thread(target=worker_b)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=20)
            assert not thread.is_alive()

        assert len(claimed.get("a", [])) == 1
        assert claimed.get("b") == []
        with Session(engine) as check:
            row = check.get(OutboxEvent, UUID(claimed["a"][0]))
            assert row is not None
            assert row.published_at is None
