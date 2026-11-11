"""Hosted runners for pending orders and price alerts (audits P0-1, P0-2)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlmodel import Session, select

from stockviz import cli
from stockviz.models import Alert, AlertDirection, PendingOrder, PriceBar, Symbol, User
from stockviz.models.order import OrderStatus, OrderType
from stockviz.models.portfolio import TradeSide
from stockviz.services.ingest.bar_semantics import latest_completed_session
from stockviz.services.trading import ensure_default_portfolio

MONDAY = datetime(2025, 4, 7)
FRIDAY = datetime(2025, 4, 4)
THURSDAY = datetime(2025, 4, 3)
MONDAY_CRON = datetime(2025, 4, 7, 22, 0)  # the 22:00 UTC cron (18:00 EDT), naive UTC


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        # Wednesday 22:00 UTC is 17:00 in New York: Wednesday is complete (MD-3).
        (datetime(2026, 11, 11, 22, 0, tzinfo=UTC), date(2026, 11, 11)),
        # Wednesday 16:30 New York (21:30 UTC): not yet, so Tuesday.
        (datetime(2026, 11, 11, 21, 30, tzinfo=UTC), date(2026, 11, 10)),
        # Monday before the close: Friday's session.
        (datetime(2026, 11, 9, 15, 0, tzinfo=UTC), date(2026, 11, 6)),
        # Weekend: Friday.
        (datetime(2026, 11, 7, 12, 0, tzinfo=UTC), date(2026, 11, 6)),
        (datetime(2026, 11, 8, 12, 0, tzinfo=UTC), date(2026, 11, 6)),
        # 03:00 UTC Thursday is Wednesday 22:00 in New York: Wednesday.
        (datetime(2026, 11, 12, 3, 0, tzinfo=UTC), date(2026, 11, 11)),
    ],
)
def test_latest_completed_session_matches_what_ingest_can_store(now, expected) -> None:
    assert latest_completed_session(now) == expected


def _setup(session: Session, *, bar_ts: datetime) -> int:
    session.add(Symbol(ticker="AAPL", name="Apple"))
    user = User(email="nightly@stockviz.dev", name="Nightly")
    session.add(user)
    session.commit()
    session.add(
        PriceBar(
            ticker="AAPL",
            ts=bar_ts,
            interval="1d",
            open=Decimal(100),
            high=Decimal(100),
            low=Decimal(100),
            close=Decimal(100),
            volume=1_000,
            source="test",
        )
    )
    session.commit()
    assert user.id is not None
    portfolio = ensure_default_portfolio(session, user.id)
    assert portfolio.id is not None
    order = PendingOrder(
        portfolio_id=portfolio.id,
        ticker="AAPL",
        side=TradeSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal(1),
        limit_price=Decimal(150),  # close 100 <= 150: triggers
    )
    session.add(order)
    session.commit()
    assert order.id is not None
    return order.id


def _status(engine, order_id: int) -> OrderStatus:
    with Session(engine) as session:
        order = session.get(PendingOrder, order_id)
        assert order is not None
        return order.status


def test_settle_orders_fills_against_the_session_the_cron_has_stored(
    engine, monkeypatch, capsys
) -> None:
    """Monday's cron stores Monday's session (MD-3) and settles against it."""
    monkeypatch.setattr(cli, "engine", engine)
    monkeypatch.setattr("stockviz._time.utcnow", lambda: MONDAY_CRON)
    with Session(engine) as session:
        order_id = _setup(session, bar_ts=MONDAY)

    assert cli.main(["settle-orders"]) == 0
    assert "against the 2025-04-07 session" in capsys.readouterr().out
    assert _status(engine, order_id) == OrderStatus.FILLED


def test_settle_orders_waits_when_the_price_refresh_missed_a_session(engine, monkeypatch) -> None:
    """Only Friday's bar on Monday night: no fill at a stale close."""
    monkeypatch.setattr(cli, "engine", engine)
    monkeypatch.setattr("stockviz._time.utcnow", lambda: MONDAY_CRON)
    with Session(engine) as session:
        order_id = _setup(session, bar_ts=FRIDAY)

    assert cli.main(["settle-orders"]) == 0
    assert _status(engine, order_id) == OrderStatus.PENDING


def test_settle_orders_takes_an_explicit_session(engine, monkeypatch) -> None:
    monkeypatch.setattr(cli, "engine", engine)
    with Session(engine) as session:
        order_id = _setup(session, bar_ts=THURSDAY)

    assert cli.main(["settle-orders", "--session-date", "2025-04-03"]) == 0
    assert _status(engine, order_id) == OrderStatus.FILLED


def test_evaluate_alerts_triggers_crossed_targets(engine, monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "engine", engine)
    with Session(engine) as session:
        _setup(session, bar_ts=FRIDAY)
        owner = session.exec(select(User)).one()
        assert owner.id is not None
        session.add(
            Alert(
                user_id=owner.id,
                ticker="AAPL",
                direction=AlertDirection.ABOVE,
                target_price=Decimal(90),
            )
        )
        session.add(
            Alert(
                user_id=owner.id,
                ticker="AAPL",
                direction=AlertDirection.ABOVE,
                target_price=Decimal(200),
            )
        )
        session.commit()

    assert cli.main(["evaluate-alerts"]) == 0
    assert "triggered 1 alert(s)" in capsys.readouterr().out
