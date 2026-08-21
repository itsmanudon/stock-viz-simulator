"""Tests for portfolio NAV snapshots: service + /v1/portfolio/history endpoint."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient
from jose import jwt as jose_jwt
from sqlmodel import Session, select

from stockviz.models import PortfolioSnapshot, PriceBar, Symbol, TradeSide, User
from stockviz.services.trading import (
    DEFAULT_STARTING_CASH,
    ensure_default_portfolio,
    execute_trade,
    snapshot_user_navs,
    upsert_user_snapshot,
)
from stockviz.settings import get_settings

SECRET = get_settings().internal_api_token


def _auth_headers(user_id: int) -> dict[str, str]:
    token = jose_jwt.encode({"sub": str(user_id)}, SECRET, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


def _seed_aapl(session: Session, close: Decimal = Decimal("150")) -> None:
    session.add(Symbol(ticker="AAPL", name="Apple Inc."))
    session.commit()
    session.add(
        PriceBar(
            ticker="AAPL",
            ts=datetime(2025, 4, 10),
            interval="1d",
            open=close,
            high=close,
            low=close,
            close=close,
            volume=1_000_000,
            source="test",
        )
    )
    session.commit()


def _make_user(session: Session, email: str = "trader@stockviz.dev") -> int:
    user = User(email=email, name="Trader")
    session.add(user)
    session.commit()
    session.refresh(user)
    assert user.id is not None
    return user.id


def _reset_snapshots(session: Session, user_id: int) -> None:
    """Drop the opening snapshot seeded by ``ensure_default_portfolio``.

    Portfolio creation writes a day-zero NAV row so the equity curve starts at
    the funded balance. Tests that assert on a hand-built NAV series clear it
    first so they control the whole window.
    """
    for row in session.exec(
        select(PortfolioSnapshot).where(PortfolioSnapshot.user_id == user_id)
    ).all():
        session.delete(row)
    session.commit()


def test_upsert_user_snapshot_writes_cash_only_nav(session: Session) -> None:
    user_id = _make_user(session)
    ensure_default_portfolio(session, user_id)

    today = date(2025, 4, 10)
    snap = upsert_user_snapshot(session, user_id=user_id, snapshot_date=today)
    assert snap.date == today
    assert Decimal(snap.nav) == DEFAULT_STARTING_CASH


def test_upsert_user_snapshot_is_idempotent(session: Session) -> None:
    _seed_aapl(session)
    user_id = _make_user(session)
    execute_trade(session, user_id=user_id, ticker="AAPL", side=TradeSide.BUY, quantity=Decimal(2))
    _reset_snapshots(session, user_id)
    today = date(2025, 4, 10)
    upsert_user_snapshot(session, user_id=user_id, snapshot_date=today)
    upsert_user_snapshot(session, user_id=user_id, snapshot_date=today)

    rows = list(
        session.exec(select(PortfolioSnapshot).where(PortfolioSnapshot.user_id == user_id)).all()
    )
    assert len(rows) == 1
    # NAV = (100000 - 2*150) cash + 2*150 market value = 100000.
    assert Decimal(rows[0].nav) == DEFAULT_STARTING_CASH


def test_snapshot_user_navs_skips_users_without_portfolios(session: Session) -> None:
    # alice has a portfolio, bob doesn't (never visited /portfolio).
    alice = _make_user(session, email="alice@stockviz.dev")
    _make_user(session, email="bob@stockviz.dev")
    ensure_default_portfolio(session, alice)

    written = snapshot_user_navs(session, snapshot_date=date(2025, 4, 10))
    assert written == 1


def test_history_requires_auth(client: TestClient) -> None:
    assert client.get("/v1/portfolio/history").status_code == 401


def test_history_returns_empty_with_no_snapshots(session: Session, client: TestClient) -> None:
    user_id = _make_user(session)
    response = client.get("/v1/portfolio/history", headers=_auth_headers(user_id))
    assert response.status_code == 200
    assert response.json() == []


def test_history_returns_ascending_window(session: Session, client: TestClient) -> None:
    user_id = _make_user(session)
    ensure_default_portfolio(session, user_id)
    _reset_snapshots(session, user_id)

    today = date.today()
    for i in range(5):
        d = today - timedelta(days=i)
        session.add(PortfolioSnapshot(user_id=user_id, date=d, nav=Decimal(100_000 + i)))
    session.commit()

    response = client.get("/v1/portfolio/history?days=365", headers=_auth_headers(user_id))
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 5
    # Ascending by date.
    dates = [row["date"] for row in body]
    assert dates == sorted(dates)


def test_history_filters_by_days_window(session: Session, client: TestClient) -> None:
    user_id = _make_user(session)
    ensure_default_portfolio(session, user_id)
    _reset_snapshots(session, user_id)
    today = date.today()
    for offset in [0, 10, 60, 120]:
        d = today - timedelta(days=offset)
        session.add(PortfolioSnapshot(user_id=user_id, date=d, nav=Decimal(100_000)))
    session.commit()

    response = client.get("/v1/portfolio/history?days=30", headers=_auth_headers(user_id))
    body = response.json()
    # Only the offset=0 and offset=10 rows fall inside the 30-day window.
    assert len(body) == 2


def test_history_isolated_per_user(session: Session, client: TestClient) -> None:
    alice = _make_user(session, email="alice@stockviz.dev")
    bob = _make_user(session, email="bob@stockviz.dev")
    today = date.today()
    session.add(PortfolioSnapshot(user_id=alice, date=today, nav=Decimal(123)))
    session.add(PortfolioSnapshot(user_id=bob, date=today, nav=Decimal(456)))
    session.commit()

    alice_body = client.get("/v1/portfolio/history", headers=_auth_headers(alice)).json()
    bob_body = client.get("/v1/portfolio/history", headers=_auth_headers(bob)).json()
    assert len(alice_body) == 1 and Decimal(alice_body[0]["nav"]) == Decimal(123)
    assert len(bob_body) == 1 and Decimal(bob_body[0]["nav"]) == Decimal(456)
