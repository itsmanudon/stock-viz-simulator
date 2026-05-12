"""HTTP-level tests for /v1/alerts + the scheduler-side evaluator."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from fastapi.testclient import TestClient
from jose import jwt as jose_jwt
from sqlmodel import Session

from stockviz.models import Alert, AlertDirection, PriceBar, Symbol, User
from stockviz.services.alerts import evaluate_pending_alerts
from stockviz.settings import get_settings

SECRET = get_settings().internal_api_token


def _auth_headers(user_id: int) -> dict[str, str]:
    token = jose_jwt.encode({"sub": str(user_id)}, SECRET, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


def _seed_symbol(session: Session, ticker: str = "AAPL", close: Decimal = Decimal("150")) -> None:
    session.add(Symbol(ticker=ticker, name=f"{ticker} Inc."))
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
            volume=1_000_000,
            source="test",
        )
    )
    session.commit()


def _make_user(session: Session, email: str = "watcher@stockviz.dev") -> int:
    user = User(email=email, name="Watcher")
    session.add(user)
    session.commit()
    session.refresh(user)
    assert user.id is not None
    return user.id


def test_alerts_require_auth(client: TestClient) -> None:
    assert client.get("/v1/alerts").status_code == 401
    assert client.post("/v1/alerts", json={}).status_code == 401
    assert client.delete("/v1/alerts/1").status_code == 401
    assert client.post("/v1/alerts/1/dismiss").status_code == 401


def test_create_then_list(session: Session, client: TestClient) -> None:
    _seed_symbol(session)
    user_id = _make_user(session)
    headers = _auth_headers(user_id)

    response = client.post(
        "/v1/alerts",
        headers=headers,
        json={"ticker": "aapl", "direction": "above", "target_price": "160"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["ticker"] == "AAPL"
    assert body["direction"] == "above"
    assert Decimal(body["target_price"]) == Decimal("160")
    assert body["triggered_at"] is None

    listed = client.get("/v1/alerts", headers=headers).json()
    assert len(listed) == 1


def test_create_rejects_unknown_ticker(session: Session, client: TestClient) -> None:
    user_id = _make_user(session)
    response = client.post(
        "/v1/alerts",
        headers=_auth_headers(user_id),
        json={"ticker": "NOPE", "direction": "above", "target_price": "10"},
    )
    assert response.status_code == 404


def test_create_rejects_nonpositive_price(session: Session, client: TestClient) -> None:
    _seed_symbol(session)
    user_id = _make_user(session)
    response = client.post(
        "/v1/alerts",
        headers=_auth_headers(user_id),
        json={"ticker": "AAPL", "direction": "above", "target_price": "0"},
    )
    assert response.status_code == 400


def test_delete_own_alert(session: Session, client: TestClient) -> None:
    _seed_symbol(session)
    user_id = _make_user(session)
    headers = _auth_headers(user_id)
    alert_id = client.post(
        "/v1/alerts",
        headers=headers,
        json={"ticker": "AAPL", "direction": "above", "target_price": "160"},
    ).json()["id"]

    assert client.delete(f"/v1/alerts/{alert_id}", headers=headers).status_code == 204
    assert client.get("/v1/alerts", headers=headers).json() == []


def test_delete_other_users_alert_is_404(session: Session, client: TestClient) -> None:
    _seed_symbol(session)
    alice = _make_user(session, email="alice@stockviz.dev")
    bob = _make_user(session, email="bob@stockviz.dev")
    alert_id = client.post(
        "/v1/alerts",
        headers=_auth_headers(alice),
        json={"ticker": "AAPL", "direction": "above", "target_price": "160"},
    ).json()["id"]

    response = client.delete(f"/v1/alerts/{alert_id}", headers=_auth_headers(bob))
    assert response.status_code == 404


def test_evaluator_triggers_alerts_when_close_crosses(session: Session, client: TestClient) -> None:
    _seed_symbol(session, "AAPL", close=Decimal("150"))
    user_id = _make_user(session)
    headers = _auth_headers(user_id)

    # Above-160 should NOT trigger at close=150.
    above_id = client.post(
        "/v1/alerts",
        headers=headers,
        json={"ticker": "AAPL", "direction": "above", "target_price": "160"},
    ).json()["id"]
    # Below-160 SHOULD trigger at close=150.
    below_id = client.post(
        "/v1/alerts",
        headers=headers,
        json={"ticker": "AAPL", "direction": "below", "target_price": "160"},
    ).json()["id"]

    triggered = evaluate_pending_alerts(session)
    assert triggered == 1

    above = session.get(Alert, above_id)
    below = session.get(Alert, below_id)
    assert above is not None and above.triggered_at is None
    assert below is not None and below.triggered_at is not None


def test_dismiss_triggered_alert(session: Session, client: TestClient) -> None:
    _seed_symbol(session, "AAPL", close=Decimal("200"))
    user_id = _make_user(session)
    headers = _auth_headers(user_id)
    alert_id = client.post(
        "/v1/alerts",
        headers=headers,
        json={"ticker": "AAPL", "direction": "above", "target_price": "160"},
    ).json()["id"]

    evaluate_pending_alerts(session)
    response = client.post(f"/v1/alerts/{alert_id}/dismiss", headers=headers)
    assert response.status_code == 200
    assert response.json()["dismissed_at"] is not None


def test_dismiss_pending_alert_is_422(session: Session, client: TestClient) -> None:
    _seed_symbol(session, "AAPL", close=Decimal("150"))
    user_id = _make_user(session)
    headers = _auth_headers(user_id)
    alert_id = client.post(
        "/v1/alerts",
        headers=headers,
        json={"ticker": "AAPL", "direction": "above", "target_price": "999"},
    ).json()["id"]

    response = client.post(f"/v1/alerts/{alert_id}/dismiss", headers=headers)
    assert response.status_code == 422


def test_evaluator_only_runs_against_pending(session: Session) -> None:
    """Already-triggered alerts shouldn't be re-evaluated."""
    _seed_symbol(session, "AAPL", close=Decimal("150"))
    user_id = _make_user(session)

    a = Alert(
        user_id=user_id,
        ticker="AAPL",
        direction=AlertDirection.BELOW,
        target_price=Decimal("160"),
        triggered_at=datetime(2025, 4, 9),
    )
    session.add(a)
    session.commit()

    triggered = evaluate_pending_alerts(session)
    assert triggered == 0
