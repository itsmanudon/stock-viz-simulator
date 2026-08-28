"""PostgreSQL concurrent next-bar advance (SIM-05)."""

from __future__ import annotations

import threading
from datetime import datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlmodel import Session, select

from stockviz.models import PriceBar, ReplaySession, Symbol, User
from stockviz.services.replay import advance_replay_session, create_replay_session
from tests.pg_scratch import postgres_admin_url, scratch_postgres_engine

pytestmark = pytest.mark.skipif(
    postgres_admin_url() is None,
    reason="DATABASE_URL is not PostgreSQL",
)

DAY1 = datetime(2024, 6, 3)
DAY2 = datetime(2024, 6, 4)
DAY3 = datetime(2024, 6, 5)


def test_two_advances_serialize_onto_successive_bars() -> None:
    with scratch_postgres_engine() as engine:
        with Session(engine) as setup:
            user = User(email=f"replay-lock-{uuid4().hex}@stockviz.dev", name="lock")
            setup.add(user)
            setup.commit()
            setup.refresh(user)
            assert user.id is not None
            user_id = user.id
            setup.add(Symbol(ticker="AAPL", name="Apple", currency="USD"))
            setup.commit()
            for ts, close in ((DAY1, "100"), (DAY2, "120"), (DAY3, "80")):
                setup.add(
                    PriceBar(
                        ticker="AAPL",
                        ts=ts,
                        interval="1d",
                        open=Decimal(close),
                        high=Decimal(close),
                        low=Decimal(close),
                        close=Decimal(close),
                        volume=1000,
                        source="test",
                    )
                )
            setup.commit()
            replay = create_replay_session(
                setup, user_id=user_id, ticker="AAPL", start_at=DAY1, end_at=DAY3
            )
            assert replay.id is not None
            session_id = replay.id

        barrier = threading.Barrier(2, timeout=15)
        errors: list[BaseException] = []

        def worker() -> None:
            try:
                with Session(engine) as db:
                    row = db.get(ReplaySession, session_id)
                    assert row is not None
                    barrier.wait()
                    advance_replay_session(db, replay=row)
            except BaseException as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=20)

        assert errors == []
        with Session(engine) as db:
            row = db.get(ReplaySession, session_id)
            assert row is not None
            assert row.current_at == DAY3
            assert row.status == "completed"
            assert db.exec(select(ReplaySession)).first() is not None
