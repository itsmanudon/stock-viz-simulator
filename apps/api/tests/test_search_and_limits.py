"""Symbol typeahead and the per-user alert cap."""

from __future__ import annotations

from decimal import Decimal

from fastapi.testclient import TestClient
from jose import jwt as jose_jwt
from sqlmodel import Session

from stockviz.models import Alert, AlertDirection, Symbol, User
from stockviz.routers.alerts import MAX_ACTIVE_ALERTS_PER_USER
from stockviz.settings import get_settings

SECRET = get_settings().internal_api_token


def _auth(user_id: int) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {jose_jwt.encode({'sub': str(user_id)}, SECRET, algorithm='HS256')}"
    }


def _user(session: Session) -> int:
    user = User(email="alerts@stockviz.dev", name="Alerts")
    session.add(user)
    session.commit()
    session.refresh(user)
    assert user.id is not None
    return user.id


def _universe(session: Session) -> None:
    session.add_all(
        [
            Symbol(ticker="AAPL", name="Apple Inc."),
            Symbol(ticker="AA", name="Alcoa Corporation"),
            Symbol(ticker="MSFT", name="Microsoft Corporation"),
            Symbol(ticker="PINEAPPLE", name="Pineapple Holdings", is_active=False),
        ]
    )
    session.commit()


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


def test_search_ranks_exact_ticker_first(session: Session, client: TestClient) -> None:
    _universe(session)
    body = client.get("/v1/symbols/search", params={"q": "AA"}).json()
    # Exact match beats the prefix match, even though AAPL sorts first
    # alphabetically among the two.
    assert [r["ticker"] for r in body][:2] == ["AA", "AAPL"]


def test_search_matches_company_name(session: Session, client: TestClient) -> None:
    _universe(session)
    body = client.get("/v1/symbols/search", params={"q": "microsoft"}).json()
    assert [r["ticker"] for r in body] == ["MSFT"]


def test_search_is_case_insensitive(session: Session, client: TestClient) -> None:
    _universe(session)
    assert client.get("/v1/symbols/search", params={"q": "aapl"}).json()[0]["ticker"] == "AAPL"


def test_search_excludes_inactive_symbols(session: Session, client: TestClient) -> None:
    _universe(session)
    tickers = [r["ticker"] for r in client.get("/v1/symbols/search", params={"q": "APPLE"}).json()]
    assert "PINEAPPLE" not in tickers
    assert "AAPL" in tickers


def test_search_honours_limit(session: Session, client: TestClient) -> None:
    _universe(session)
    body = client.get("/v1/symbols/search", params={"q": "A", "limit": 1}).json()
    assert len(body) == 1


def test_search_does_not_shadow_the_ticker_detail_route(
    session: Session, client: TestClient
) -> None:
    """`/search` is registered before `/{ticker}`; without that ordering the
    catch-all would swallow it and return a 404 for symbol "SEARCH"."""
    _universe(session)
    assert client.get("/v1/symbols/search", params={"q": "AAPL"}).status_code == 200
    assert client.get("/v1/symbols/AAPL").status_code == 200


def test_search_requires_a_query(session: Session, client: TestClient) -> None:
    _universe(session)
    assert client.get("/v1/symbols/search").status_code == 422
    assert client.get("/v1/symbols/search", params={"q": ""}).status_code == 422


# ---------------------------------------------------------------------------
# Alert cap
# ---------------------------------------------------------------------------


def test_alert_creation_is_capped_per_user(session: Session, client: TestClient) -> None:
    """Unbounded alerts made the hourly evaluation pass grow without limit."""
    _universe(session)
    user_id = _user(session)

    session.add_all(
        [
            Alert(
                user_id=user_id,
                ticker="AAPL",
                direction=AlertDirection.ABOVE,
                target_price=Decimal(100 + i),
            )
            for i in range(MAX_ACTIVE_ALERTS_PER_USER)
        ]
    )
    session.commit()

    response = client.post(
        "/v1/alerts",
        json={"ticker": "AAPL", "direction": "above", "target_price": "999"},
        headers=_auth(user_id),
    )
    assert response.status_code == 409
    assert "active alerts" in response.json()["detail"]


def test_triggered_alerts_do_not_count_toward_the_cap(session: Session, client: TestClient) -> None:
    """Triggered alerts are history — the user clears them by dismissing."""
    from stockviz._time import utcnow

    _universe(session)
    user_id = _user(session)

    session.add_all(
        [
            Alert(
                user_id=user_id,
                ticker="AAPL",
                direction=AlertDirection.ABOVE,
                target_price=Decimal(100 + i),
                triggered_at=utcnow(),
            )
            for i in range(MAX_ACTIVE_ALERTS_PER_USER)
        ]
    )
    session.commit()

    response = client.post(
        "/v1/alerts",
        json={"ticker": "AAPL", "direction": "above", "target_price": "999"},
        headers=_auth(user_id),
    )
    assert response.status_code == 201
