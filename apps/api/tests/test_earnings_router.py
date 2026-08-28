"""HTTP contract tests for the authenticated earnings calendar."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from fastapi.testclient import TestClient
from jose import jwt as jose_jwt
from sqlmodel import Session

from stockviz.models import (
    EarningsEvent,
    Portfolio,
    Position,
    Symbol,
    User,
    Watchlist,
    WatchlistItem,
)
from stockviz.settings import get_settings

SECRET = get_settings().internal_api_token


def _auth_headers(user_id: int) -> dict[str, str]:
    token = jose_jwt.encode({"sub": str(user_id)}, SECRET, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


def _user(session: Session, email: str) -> int:
    user = User(email=email, name=email.split("@")[0])
    session.add(user)
    session.commit()
    session.refresh(user)
    assert user.id is not None
    return user.id


def test_earnings_requires_auth(client: TestClient) -> None:
    assert client.get("/v1/earnings").status_code == 401


def test_earnings_returns_derived_result_and_date_filter(
    session: Session, client: TestClient
) -> None:
    session.add(Symbol(ticker="AAPL", name="Apple Inc."))
    user_id = _user(session, "calendar@stockviz.dev")
    session.add(
        EarningsEvent(
            ticker="AAPL",
            event_date=date(2026, 8, 5),
            eps_estimate=Decimal("1.00"),
            eps_actual=Decimal("1.12"),
            source="fixture",
            fetched_at=datetime(2026, 8, 1),
        )
    )
    session.commit()

    response = client.get(
        "/v1/earnings?from=2026-08-01&to=2026-08-31",
        headers=_auth_headers(user_id),
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["ticker"] == "AAPL"
    assert body[0]["result"] == "beat"

    assert (
        client.get(
            "/v1/earnings?from=2026-09-01&to=2026-09-30",
            headers=_auth_headers(user_id),
        ).json()
        == []
    )


def test_earnings_holdings_scope_is_private_to_user(session: Session, client: TestClient) -> None:
    session.add(Symbol(ticker="AAPL", name="Apple Inc."))
    owner = _user(session, "owner@stockviz.dev")
    other = _user(session, "other@stockviz.dev")
    portfolio = Portfolio(user_id=owner, name="Default", cash_balance=Decimal("100000"))
    session.add(portfolio)
    session.commit()
    session.refresh(portfolio)
    session.add(
        Position(
            portfolio_id=portfolio.id, ticker="AAPL", quantity=Decimal("2"), avg_cost=Decimal("100")
        )
    )  # type: ignore[arg-type]
    session.add(
        EarningsEvent(
            ticker="AAPL",
            event_date=date(2026, 8, 5),
            report_time="AMC",
            source="fixture",
            fetched_at=datetime(2026, 8, 1),
        )
    )
    session.commit()

    path = "/v1/earnings?from=2026-08-01&to=2026-08-31&scope=holdings"
    assert len(client.get(path, headers=_auth_headers(owner)).json()) == 1
    assert client.get(path, headers=_auth_headers(other)).json() == []


def test_earnings_rejects_unbounded_range(session: Session, client: TestClient) -> None:
    user_id = _user(session, "range@stockviz.dev")
    response = client.get(
        "/v1/earnings?from=2025-01-01&to=2026-08-31",
        headers=_auth_headers(user_id),
    )
    assert response.status_code == 422


def test_earnings_watchlist_scope_is_private_to_user(session: Session, client: TestClient) -> None:
    session.add(Symbol(ticker="MSFT", name="Microsoft Corporation"))
    owner = _user(session, "watcher@stockviz.dev")
    other = _user(session, "observer@stockviz.dev")
    watchlist = Watchlist(user_id=owner, name="Long term")
    session.add(watchlist)
    session.commit()
    session.refresh(watchlist)
    session.add(WatchlistItem(watchlist_id=watchlist.id, ticker="MSFT"))  # type: ignore[arg-type]
    session.add(
        EarningsEvent(
            ticker="MSFT",
            event_date=date(2026, 8, 12),
            report_time="BMO",
            source="fixture",
            fetched_at=datetime(2026, 8, 1),
        )
    )
    session.commit()

    path = "/v1/earnings?from=2026-08-01&to=2026-08-31&scope=watchlist"
    assert len(client.get(path, headers=_auth_headers(owner)).json()) == 1
    assert client.get(path, headers=_auth_headers(other)).json() == []
