"""HTTP tests for replay forensics and journal (SIM-07)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from fastapi.testclient import TestClient
from jose import jwt as jose_jwt
from sqlmodel import Session

from stockviz.models import PriceBar, Symbol, User
from stockviz.settings import get_settings

SECRET = get_settings().internal_api_token
DAY1 = "2024-06-03T00:00:00"
DAY2 = "2024-06-04T00:00:00"
DAY3 = "2024-06-05T00:00:00"
DAY4 = "2024-06-06T00:00:00"


def _auth_headers(user_id: int) -> dict[str, str]:
    token = jose_jwt.encode({"sub": str(user_id)}, SECRET, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


def _make_user(session: Session, email: str) -> int:
    user = User(email=email, name="Replay Forensics")
    session.add(user)
    session.commit()
    session.refresh(user)
    assert user.id is not None
    return user.id


def _bar(
    ts: datetime,
    close: Decimal,
    *,
    high: Decimal | None = None,
    low: Decimal | None = None,
) -> PriceBar:
    return PriceBar(
        ticker="AAPL",
        ts=ts,
        interval="1d",
        open=close,
        high=high if high is not None else close,
        low=low if low is not None else close,
        close=close,
        volume=1_000_000,
        source="test",
    )


def _seed(session: Session) -> None:
    session.add(Symbol(ticker="AAPL", name="Apple", currency="USD"))
    session.commit()
    session.add_all(
        [
            _bar(datetime(2024, 6, 3), Decimal("100"), high=Decimal("103"), low=Decimal("98")),
            _bar(datetime(2024, 6, 4), Decimal("102"), high=Decimal("110"), low=Decimal("90")),
            _bar(datetime(2024, 6, 5), Decimal("105"), high=Decimal("106"), low=Decimal("104")),
            _bar(datetime(2024, 6, 6), Decimal("50"), high=Decimal("10000"), low=Decimal("1")),
        ]
    )
    session.commit()


def _create(client: TestClient, headers: dict[str, str], end: str = DAY3):
    return client.post(
        "/v1/replay/sessions",
        headers=headers,
        json={"ticker": "AAPL", "start_at": DAY1, "end_at": end, "starting_cash": "100000"},
    )


def test_forensics_requires_auth(client: TestClient) -> None:
    response = client.get("/v1/replay/sessions/1/forensics")
    assert response.status_code == 401
    journal = client.get("/v1/replay/sessions/1/journal")
    assert journal.status_code == 401


def test_forensics_ownership_404(session: Session, client: TestClient) -> None:
    _seed(session)
    owner = _auth_headers(_make_user(session, "owner-forensics@stockviz.dev"))
    other = _auth_headers(_make_user(session, "other-forensics@stockviz.dev"))
    session_id = _create(client, owner).json()["id"]
    assert (
        client.get(f"/v1/replay/sessions/{session_id}/forensics", headers=other).status_code == 404
    )
    assert client.get(f"/v1/replay/sessions/{session_id}/journal", headers=other).status_code == 404
    assert (
        client.put(
            f"/v1/replay/sessions/{session_id}/journal",
            headers=other,
            json={"thesis": "stolen"},
        ).status_code
        == 404
    )


def test_forensics_mae_mfe_and_future_leak(session: Session, client: TestClient) -> None:
    _seed(session)
    headers = _auth_headers(_make_user(session, "mae@stockviz.dev"))
    session_id = _create(client, headers, end=DAY4).json()["id"]
    buy = client.post(
        f"/v1/replay/sessions/{session_id}/orders",
        headers=headers,
        json={"side": "buy", "order_type": "market", "quantity": "1"},
    )
    assert buy.status_code == 200
    client.post(f"/v1/replay/sessions/{session_id}/advance", headers=headers)
    client.post(f"/v1/replay/sessions/{session_id}/advance", headers=headers)
    sell = client.post(
        f"/v1/replay/sessions/{session_id}/orders",
        headers=headers,
        json={"side": "sell", "order_type": "market", "quantity": "1"},
    )
    assert sell.status_code == 200
    body = client.get(f"/v1/replay/sessions/{session_id}/forensics", headers=headers).json()
    assert body["analysis_scope"] == "so_far"
    assert len(body["episodes"]) == 1
    episode = body["episodes"][0]
    assert episode["status"] == "closed"
    assert Decimal(episode["mae_pct"]) == Decimal("-10.0000")
    assert Decimal(episode["mfe_pct"]) == Decimal("10.0000")
    assert Decimal(episode["entry_price"]) == Decimal("100")
    assert Decimal(episode["exit_price"]) == Decimal("105")
    assert episode["fills"][0]["profile_name"] == "legacy_close"
    assert "Uses stored 1d close" in episode["fills"][0]["assumptions"]
    # Day4 is stored but not yet visible.
    assert not body["analysis_at"].startswith("2024-06-06")


def test_open_episode_ignores_future_seeded_extreme(session: Session, client: TestClient) -> None:
    _seed(session)
    headers = _auth_headers(_make_user(session, "open-ep@stockviz.dev"))
    session_id = _create(client, headers, end=DAY4).json()["id"]
    client.post(
        f"/v1/replay/sessions/{session_id}/orders",
        headers=headers,
        json={"side": "buy", "order_type": "market", "quantity": "1"},
    )
    client.post(f"/v1/replay/sessions/{session_id}/advance", headers=headers)
    client.post(f"/v1/replay/sessions/{session_id}/advance", headers=headers)
    body = client.get(f"/v1/replay/sessions/{session_id}/forensics", headers=headers).json()
    episode = body["episodes"][0]
    assert episode["status"] == "open"
    assert episode["exit_price"] is None
    assert Decimal(episode["mae_pct"]) == Decimal("-10.0000")
    assert Decimal(episode["mfe_pct"]) == Decimal("10.0000")
    assert Decimal(episode["mae_pct"]) != Decimal("-99")


def test_empty_session_benchmark(session: Session, client: TestClient) -> None:
    _seed(session)
    headers = _auth_headers(_make_user(session, "empty-bh@stockviz.dev"))
    session_id = _create(client, headers).json()["id"]
    client.post(f"/v1/replay/sessions/{session_id}/advance", headers=headers)
    done = client.post(f"/v1/replay/sessions/{session_id}/advance", headers=headers)
    assert done.json()["status"] == "completed"
    body = client.get(f"/v1/replay/sessions/{session_id}/forensics", headers=headers).json()
    assert body["analysis_scope"] == "final"
    assert Decimal(body["replay_return_pct"]) == Decimal("0")
    assert Decimal(body["buy_hold_return_pct"]) == Decimal("5.0000")
    assert Decimal(body["excess_return_pct"]) == Decimal("-5.0000")
    assert body["episodes_count"] == 0


def test_cancelled_forensics_stop_at_current(session: Session, client: TestClient) -> None:
    _seed(session)
    headers = _auth_headers(_make_user(session, "cancel-f@stockviz.dev"))
    session_id = _create(client, headers, end=DAY4).json()["id"]
    client.post(
        f"/v1/replay/sessions/{session_id}/orders",
        headers=headers,
        json={"side": "buy", "order_type": "market", "quantity": "1"},
    )
    client.post(f"/v1/replay/sessions/{session_id}/advance", headers=headers)
    client.post(f"/v1/replay/sessions/{session_id}/cancel", headers=headers)
    body = client.get(f"/v1/replay/sessions/{session_id}/forensics", headers=headers).json()
    assert body["status"] == "cancelled"
    assert body["analysis_scope"] == "cancelled"
    assert body["analysis_at"].startswith("2024-06-04")
    assert Decimal(body["episodes"][0]["mae_pct"]) == Decimal("-10.0000")


def test_completed_does_not_use_bars_after_end(session: Session, client: TestClient) -> None:
    _seed(session)
    headers = _auth_headers(_make_user(session, "end-horizon@stockviz.dev"))
    session_id = _create(client, headers, end=DAY3).json()["id"]
    client.post(f"/v1/replay/sessions/{session_id}/advance", headers=headers)
    client.post(f"/v1/replay/sessions/{session_id}/advance", headers=headers)
    body = client.get(f"/v1/replay/sessions/{session_id}/forensics", headers=headers).json()
    assert body["status"] == "completed"
    assert body["analysis_at"].startswith("2024-06-05")
    assert Decimal(body["buy_hold_return_pct"]) == Decimal("5.0000")


def test_journal_lock_after_first_fill(session: Session, client: TestClient) -> None:
    _seed(session)
    headers = _auth_headers(_make_user(session, "journal@stockviz.dev"))
    session_id = _create(client, headers).json()["id"]
    created = client.put(
        f"/v1/replay/sessions/{session_id}/journal",
        headers=headers,
        json={
            "thesis": "Hold through the range",
            "invalidation": "Close below 90",
            "expected_holding_bars": 3,
            "confidence": 4,
        },
    )
    assert created.status_code == 200
    assert created.json()["locked"] is False
    assert created.json()["thesis"] == "Hold through the range"

    client.post(
        f"/v1/replay/sessions/{session_id}/orders",
        headers=headers,
        json={"side": "buy", "order_type": "market", "quantity": "1"},
    )
    locked = client.get(f"/v1/replay/sessions/{session_id}/journal", headers=headers).json()
    assert locked["locked"] is True

    denied = client.put(
        f"/v1/replay/sessions/{session_id}/journal",
        headers=headers,
        json={
            "thesis": "rewritten after the fill",
            "invalidation": "Close below 90",
            "expected_holding_bars": 3,
            "confidence": 4,
        },
    )
    assert denied.status_code == 409

    reflection = client.put(
        f"/v1/replay/sessions/{session_id}/journal",
        headers=headers,
        json={
            "thesis": "Hold through the range",
            "invalidation": "Close below 90",
            "expected_holding_bars": 3,
            "confidence": 4,
            "reflection": "Size was too large.",
        },
    )
    assert reflection.status_code == 200
    assert reflection.json()["reflection"] == "Size was too large."
    assert reflection.json()["thesis"] == "Hold through the range"
