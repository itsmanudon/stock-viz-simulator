"""HTTP tests for /v1/replay (SIM-05)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from fastapi.testclient import TestClient
from jose import jwt as jose_jwt
from sqlmodel import Session, select

from stockviz.models import PriceBar, ReplayFill, SimulatedExecution, Symbol, Trade, User
from stockviz.settings import get_settings

SECRET = get_settings().internal_api_token
DAY1 = "2024-06-03T00:00:00"
DAY2 = "2024-06-04T00:00:00"
DAY3 = "2024-06-05T00:00:00"


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


def _seed(session: Session) -> None:
    session.add(Symbol(ticker="AAPL", name="Apple", currency="USD"))
    session.commit()
    closes = {
        datetime(2024, 6, 3): Decimal("100"),
        datetime(2024, 6, 4): Decimal("120"),
        datetime(2024, 6, 5): Decimal("80"),
    }
    for ts, close in closes.items():
        session.add(
            PriceBar(
                ticker="AAPL",
                ts=ts,
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


def _create(client: TestClient, headers: dict[str, str], **extra):
    payload = {"ticker": "AAPL", "start_at": DAY1, "end_at": DAY3, **extra}
    return client.post("/v1/replay/sessions", headers=headers, json=payload)


def test_replay_requires_auth(client: TestClient) -> None:
    response = client.get("/v1/replay/sessions")
    assert response.status_code == 401


def test_create_market_order_history_and_advance(session: Session, client: TestClient) -> None:
    _seed(session)
    user_id = _make_user(session)
    headers = _auth_headers(user_id)

    created = _create(client, headers)
    assert created.status_code == 201
    body = created.json()
    assert body["ticker"] == "AAPL"
    assert body["profile_name"] == "legacy_close"
    assert body["status"] == "active"
    assert body["has_next"] is True
    session_id = body["id"]

    market = client.get(f"/v1/replay/sessions/{session_id}/market", headers=headers)
    assert market.status_code == 200
    assert market.json()["bar"]["close"] in {"100", "100.000000"}
    assert market.json()["has_next"] is True

    history = client.get(f"/v1/replay/sessions/{session_id}/history", headers=headers)
    assert history.status_code == 200
    assert len(history.json()) == 1

    submitted = client.post(
        f"/v1/replay/sessions/{session_id}/orders",
        headers=headers,
        json={"side": "buy", "order_type": "market", "quantity": "2"},
    )
    assert submitted.status_code == 200
    payload = submitted.json()
    assert payload["decision"]["status"] == "filled"
    assert Decimal(payload["decision"]["fill_price"]) == Decimal("100")
    assert Decimal(payload["session"]["cash_balance"]) == Decimal("100000") - Decimal("200")

    forged = client.post(
        f"/v1/replay/sessions/{session_id}/orders",
        headers=headers,
        json={
            "side": "buy",
            "quantity": "1",
            "snapshot": {
                "open": "99999",
                "high": "99999",
                "low": "99999",
                "close": "99999",
                "volume": "1",
            },
        },
    )
    assert forged.status_code == 422

    advanced = client.post(f"/v1/replay/sessions/{session_id}/advance", headers=headers)
    assert advanced.status_code == 200
    assert advanced.json()["current_at"].startswith("2024-06-04")
    history = client.get(f"/v1/replay/sessions/{session_id}/history", headers=headers)
    assert len(history.json()) == 2
    assert all(row["ts"].startswith("2024-06-0") for row in history.json())
    assert not any(row["ts"].startswith("2024-06-05") for row in history.json())

    fills = client.get(f"/v1/replay/sessions/{session_id}/fills", headers=headers)
    assert fills.status_code == 200
    assert len(fills.json()) == 1
    assert session.exec(select(Trade)).first() is None
    assert session.exec(select(SimulatedExecution)).first() is None
    assert session.exec(select(ReplayFill)).first() is not None


def test_advance_to_end_then_409(session: Session, client: TestClient) -> None:
    _seed(session)
    headers = _auth_headers(_make_user(session))
    session_id = _create(client, headers).json()["id"]
    first = client.post(f"/v1/replay/sessions/{session_id}/advance", headers=headers)
    assert first.status_code == 200
    last = client.post(f"/v1/replay/sessions/{session_id}/advance", headers=headers)
    assert last.status_code == 200
    assert last.json()["status"] == "completed"
    again = client.post(f"/v1/replay/sessions/{session_id}/advance", headers=headers)
    assert again.status_code == 409
    order = client.post(
        f"/v1/replay/sessions/{session_id}/orders",
        headers=headers,
        json={"side": "buy", "quantity": "1"},
    )
    assert order.status_code == 409


def test_clock_endpoint_removed(session: Session, client: TestClient) -> None:
    _seed(session)
    headers = _auth_headers(_make_user(session))
    session_id = _create(client, headers).json()["id"]
    response = client.post(
        f"/v1/replay/sessions/{session_id}/clock",
        headers=headers,
        json={"now": DAY2},
    )
    assert response.status_code == 404


def test_unknown_ticker_returns_404(session: Session, client: TestClient) -> None:
    user_id = _make_user(session)
    response = _create(client, _auth_headers(user_id))
    # no symbols seeded
    assert response.status_code == 404


def test_cancelled_session_returns_409(session: Session, client: TestClient) -> None:
    _seed(session)
    headers = _auth_headers(_make_user(session))
    session_id = _create(client, headers).json()["id"]
    cancelled = client.post(f"/v1/replay/sessions/{session_id}/cancel", headers=headers)
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    advance = client.post(f"/v1/replay/sessions/{session_id}/advance", headers=headers)
    assert advance.status_code == 409


def test_missing_session_returns_404(session: Session, client: TestClient) -> None:
    user_id = _make_user(session)
    headers = _auth_headers(user_id)
    assert client.get("/v1/replay/sessions/999999", headers=headers).status_code == 404
    assert client.get("/v1/replay/sessions/999999/market", headers=headers).status_code == 404
    assert client.get("/v1/replay/sessions/999999/history", headers=headers).status_code == 404
    assert client.post("/v1/replay/sessions/999999/advance", headers=headers).status_code == 404
    assert client.post("/v1/replay/sessions/999999/cancel", headers=headers).status_code == 404
    assert (
        client.post(
            "/v1/replay/sessions/999999/orders",
            headers=headers,
            json={"side": "buy", "quantity": "1"},
        ).status_code
        == 404
    )
    assert client.get("/v1/replay/sessions/999999/fills", headers=headers).status_code == 404
    assert client.get("/v1/replay/sessions/999999/summary", headers=headers).status_code == 404


def test_other_user_cannot_access_session_actions(session: Session, client: TestClient) -> None:
    _seed(session)
    owner = _make_user(session, "owner@stockviz.dev")
    other = _auth_headers(_make_user(session, "other@stockviz.dev"))
    session_id = _create(client, _auth_headers(owner)).json()["id"]
    assert client.get(f"/v1/replay/sessions/{session_id}", headers=other).status_code == 404
    assert client.get(f"/v1/replay/sessions/{session_id}/market", headers=other).status_code == 404
    assert client.get(f"/v1/replay/sessions/{session_id}/history", headers=other).status_code == 404
    assert client.get(f"/v1/replay/sessions/{session_id}/fills", headers=other).status_code == 404
    assert (
        client.post(f"/v1/replay/sessions/{session_id}/advance", headers=other).status_code == 404
    )
    assert client.post(f"/v1/replay/sessions/{session_id}/cancel", headers=other).status_code == 404
    assert (
        client.post(
            f"/v1/replay/sessions/{session_id}/orders",
            headers=other,
            json={"side": "buy", "quantity": "1"},
        ).status_code
        == 404
    )
    assert client.get(f"/v1/replay/sessions/{session_id}/summary", headers=other).status_code == 404


def test_list_is_lightweight_and_availability_works(session: Session, client: TestClient) -> None:
    _seed(session)
    headers = _auth_headers(_make_user(session))
    created = _create(client, headers)
    assert created.status_code == 201
    listed = client.get("/v1/replay/sessions", headers=headers)
    assert listed.status_code == 200
    row = listed.json()[0]
    assert "positions" not in row
    assert row["ticker"] == "AAPL"
    assert row["has_next"] is True

    available = client.get("/v1/replay/availability?ticker=AAPL", headers=headers)
    assert available.status_code == 200
    body = available.json()
    assert body["ticker"] == "AAPL"
    assert body["bars_count"] == 3
    assert body["first_bar"].startswith("2024-06-03")
    assert body["last_bar"].startswith("2024-06-05")

    missing = client.get("/v1/replay/availability?ticker=NOPE", headers=headers)
    assert missing.status_code == 404


def test_summary_and_history_never_include_future_bars(
    session: Session, client: TestClient
) -> None:
    _seed(session)
    headers = _auth_headers(_make_user(session))
    session_id = _create(client, headers).json()["id"]
    client.post(
        f"/v1/replay/sessions/{session_id}/orders",
        headers=headers,
        json={"side": "buy", "quantity": "1"},
    )
    client.post(f"/v1/replay/sessions/{session_id}/advance", headers=headers)

    summary = client.get(f"/v1/replay/sessions/{session_id}/summary", headers=headers)
    assert summary.status_code == 200
    payload = summary.json()
    assert Decimal(payload["current_close"]) == Decimal("120")
    assert Decimal(payload["visible_high"]) == Decimal("120")
    assert Decimal(payload["unrealized_pnl"]) == Decimal("20")

    history = client.get(f"/v1/replay/sessions/{session_id}/history", headers=headers).json()
    closes = [Decimal(row["close"]) for row in history]
    assert Decimal("80") not in closes
    assert max(closes) == Decimal("120")
    market = client.get(f"/v1/replay/sessions/{session_id}/market", headers=headers).json()
    assert Decimal(market["bar"]["close"]) == Decimal("120")
    detail = client.get(f"/v1/replay/sessions/{session_id}", headers=headers).json()
    assert detail["current_at"].startswith("2024-06-04")
    assert not detail["current_at"].startswith("2024-06-05")


def test_summary_and_orders_on_terminal_sessions(session: Session, client: TestClient) -> None:
    _seed(session)
    headers = _auth_headers(_make_user(session))
    session_id = _create(client, headers).json()["id"]
    client.post(f"/v1/replay/sessions/{session_id}/advance", headers=headers)
    completed = client.post(f"/v1/replay/sessions/{session_id}/advance", headers=headers)
    assert completed.json()["status"] == "completed"
    summary = client.get(f"/v1/replay/sessions/{session_id}/summary", headers=headers)
    assert summary.status_code == 200
    assert Decimal(summary.json()["current_close"]) == Decimal("80")
    assert (
        client.post(
            f"/v1/replay/sessions/{session_id}/orders",
            headers=headers,
            json={"side": "buy", "quantity": "1"},
        ).status_code
        == 409
    )

    other = _create(client, headers).json()["id"]
    client.post(f"/v1/replay/sessions/{other}/cancel", headers=headers)
    cancelled = client.get(f"/v1/replay/sessions/{other}/summary", headers=headers)
    assert cancelled.status_code == 200
    assert client.get(f"/v1/replay/sessions/{other}", headers=headers).json()["status"] == (
        "cancelled"
    )
    assert client.post(f"/v1/replay/sessions/{other}/advance", headers=headers).status_code == 409
