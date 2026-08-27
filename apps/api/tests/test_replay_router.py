"""HTTP tests for /v1/replay (SIM-05)."""

from __future__ import annotations

from decimal import Decimal

from fastapi.testclient import TestClient
from jose import jwt as jose_jwt
from sqlmodel import Session, select

from stockviz.models import ReplayFill, SimulatedExecution, Trade, User
from stockviz.settings import get_settings

SECRET = get_settings().internal_api_token
CLOCK = "2024-06-03T21:00:00+00:00"


def _auth_headers(user_id: int) -> dict[str, str]:
    token = jose_jwt.encode({"sub": str(user_id)}, SECRET, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


def _make_user(session: Session, email: str = "replay-http@stockviz.dev") -> int:
    user = User(email=email, name="Replay HTTP")
    session.add(user)
    session.commit()
    session.refresh(user)
    assert user.id is not None
    return user.id


def _snapshot(close: str = "150") -> dict:
    return {
        "interval": "1d",
        "open": close,
        "high": close,
        "low": close,
        "close": close,
        "volume": "1000000",
    }


def test_replay_requires_auth(client: TestClient) -> None:
    response = client.get("/v1/replay/sessions")
    assert response.status_code == 401


def test_create_session_submit_market_and_list_fills(session: Session, client: TestClient) -> None:
    user_id = _make_user(session)
    headers = _auth_headers(user_id)

    created = client.post(
        "/v1/replay/sessions",
        headers=headers,
        json={"clock_now": CLOCK, "starting_cash": "100000.00"},
    )
    assert created.status_code == 201
    body = created.json()
    assert body["profile_name"] == "legacy_close"
    assert body["model_version"] == "v1"
    assert body["status"] == "open"
    assert body["clock_now"].startswith("2024-06-03T21:00:00")
    session_id = body["id"]

    submitted = client.post(
        f"/v1/replay/sessions/{session_id}/orders",
        headers=headers,
        json={
            "ticker": "AAPL",
            "side": "buy",
            "order_type": "market",
            "quantity": "10",
            "snapshot": _snapshot("150"),
        },
    )
    assert submitted.status_code == 200
    payload = submitted.json()
    assert payload["decision"]["status"] == "filled"
    assert payload["decision"]["fill_price"] == "150.000000" or payload["decision"][
        "fill_price"
    ].startswith("150")
    assert payload["fill"]["evaluated_at"].startswith("2024-06-03T21:00:00")
    assert payload["fill"]["profile_name"] == "legacy_close"
    assert Decimal(payload["session"]["cash_balance"]) == Decimal("100000.00") - Decimal("1500")

    fills = client.get(f"/v1/replay/sessions/{session_id}/fills", headers=headers)
    assert fills.status_code == 200
    assert len(fills.json()) == 1

    assert session.exec(select(Trade)).first() is None
    assert session.exec(select(SimulatedExecution)).first() is None
    assert session.exec(select(ReplayFill)).first() is not None


def test_lookahead_returns_400(session: Session, client: TestClient) -> None:
    user_id = _make_user(session)
    headers = _auth_headers(user_id)
    session_id = client.post(
        "/v1/replay/sessions", headers=headers, json={"clock_now": CLOCK}
    ).json()["id"]
    response = client.post(
        f"/v1/replay/sessions/{session_id}/orders",
        headers=headers,
        json={
            "ticker": "AAPL",
            "side": "buy",
            "order_type": "market",
            "quantity": "1",
            "snapshot": {**_snapshot("150"), "observed_at": "2024-06-10T21:00:00+00:00"},
        },
    )
    assert response.status_code == 400
    assert "observed_at" in response.json()["detail"]


def test_unknown_profile_returns_400(session: Session, client: TestClient) -> None:
    user_id = _make_user(session)
    response = client.post(
        "/v1/replay/sessions",
        headers=_auth_headers(user_id),
        json={"clock_now": CLOCK, "profile_name": "retail_realistic", "model_version": "v1"},
    )
    assert response.status_code == 400


def test_closed_session_returns_409(session: Session, client: TestClient) -> None:
    user_id = _make_user(session)
    headers = _auth_headers(user_id)
    session_id = client.post(
        "/v1/replay/sessions", headers=headers, json={"clock_now": CLOCK}
    ).json()["id"]
    closed = client.post(f"/v1/replay/sessions/{session_id}/close", headers=headers)
    assert closed.status_code == 200
    assert closed.json()["status"] == "closed"
    clock = client.post(
        f"/v1/replay/sessions/{session_id}/clock",
        headers=headers,
        json={"now": "2024-06-04T21:00:00+00:00"},
    )
    assert clock.status_code == 409


def test_missing_session_returns_404(session: Session, client: TestClient) -> None:
    user_id = _make_user(session)
    response = client.get("/v1/replay/sessions/999999", headers=_auth_headers(user_id))
    assert response.status_code == 404


def test_other_user_cannot_read_session(session: Session, client: TestClient) -> None:
    owner = _make_user(session, "owner@stockviz.dev")
    other = _make_user(session, "other@stockviz.dev")
    session_id = client.post(
        "/v1/replay/sessions",
        headers=_auth_headers(owner),
        json={"clock_now": CLOCK},
    ).json()["id"]
    response = client.get(f"/v1/replay/sessions/{session_id}", headers=_auth_headers(other))
    assert response.status_code == 404
