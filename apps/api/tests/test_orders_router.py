"""HTTP-level tests for /v1/orders — pending order management."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from fastapi.testclient import TestClient
from jose import jwt as jose_jwt
from sqlmodel import Session

from stockviz.models import PriceBar, Symbol, User
from stockviz.settings import get_settings

SECRET = get_settings().internal_api_token


def _auth_headers(user_id: int) -> dict[str, str]:
    token = jose_jwt.encode({"sub": str(user_id)}, SECRET, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


def _seed_market(session: Session) -> None:
    session.add(Symbol(ticker="AAPL", name="Apple Inc."))
    session.commit()
    session.add(
        PriceBar(
            ticker="AAPL",
            ts=datetime(2025, 4, 10),
            interval="1d",
            open=Decimal("145"),
            high=Decimal("151"),
            low=Decimal("144"),
            close=Decimal("150"),
            volume=1_000_000,
            source="test",
        )
    )
    session.commit()


def _make_user(session: Session) -> int:
    user = User(email="trader@stockviz.dev", name="Trader")
    session.add(user)
    session.commit()
    session.refresh(user)
    assert user.id is not None
    return user.id


# ---------------------------------------------------------------------------
# Auth guard
# ---------------------------------------------------------------------------


def test_create_order_requires_auth(client: TestClient) -> None:
    response = client.post(
        "/v1/orders",
        json={
            "ticker": "AAPL",
            "side": "buy",
            "order_type": "limit",
            "quantity": "1",
            "limit_price": "140",
        },
    )
    assert response.status_code == 401


def test_list_orders_requires_auth(client: TestClient) -> None:
    assert client.get("/v1/orders").status_code == 401


# ---------------------------------------------------------------------------
# Create order
# ---------------------------------------------------------------------------


def test_create_limit_buy_order(session: Session, client: TestClient) -> None:
    _seed_market(session)
    user_id = _make_user(session)

    response = client.post(
        "/v1/orders",
        headers=_auth_headers(user_id),
        json={
            "ticker": "AAPL",
            "side": "buy",
            "order_type": "limit",
            "quantity": "5",
            "limit_price": "140.00",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["ticker"] == "AAPL"
    assert body["side"] == "buy"
    assert body["order_type"] == "limit"
    assert Decimal(body["quantity"]) == Decimal("5")
    assert Decimal(body["limit_price"]) == Decimal("140.00")
    assert body["status"] == "pending"
    assert body["filled_at"] is None
    assert body["fill_price"] is None


def test_create_stop_loss_order(session: Session, client: TestClient) -> None:
    _seed_market(session)
    user_id = _make_user(session)

    response = client.post(
        "/v1/orders",
        headers=_auth_headers(user_id),
        json={
            "ticker": "AAPL",
            "side": "sell",
            "order_type": "stop_loss",
            "quantity": "2",
            "limit_price": "130.00",
        },
    )
    assert response.status_code == 201
    assert response.json()["order_type"] == "stop_loss"


def test_create_take_profit_order(session: Session, client: TestClient) -> None:
    _seed_market(session)
    user_id = _make_user(session)

    response = client.post(
        "/v1/orders",
        headers=_auth_headers(user_id),
        json={
            "ticker": "AAPL",
            "side": "sell",
            "order_type": "take_profit",
            "quantity": "3",
            "limit_price": "200.00",
        },
    )
    assert response.status_code == 201
    assert response.json()["order_type"] == "take_profit"


def test_create_order_unknown_symbol_returns_404(session: Session, client: TestClient) -> None:
    _make_user(session)
    user_id = 1
    session.flush()

    response = client.post(
        "/v1/orders",
        headers=_auth_headers(user_id),
        json={
            "ticker": "NOPE",
            "side": "buy",
            "order_type": "limit",
            "quantity": "1",
            "limit_price": "100",
        },
    )
    assert response.status_code == 404


def test_create_order_invalid_side_returns_400(session: Session, client: TestClient) -> None:
    _seed_market(session)
    user_id = _make_user(session)

    response = client.post(
        "/v1/orders",
        headers=_auth_headers(user_id),
        json={
            "ticker": "AAPL",
            "side": "hold",
            "order_type": "limit",
            "quantity": "1",
            "limit_price": "100",
        },
    )
    assert response.status_code == 400


def test_create_order_invalid_order_type_returns_400(session: Session, client: TestClient) -> None:
    _seed_market(session)
    user_id = _make_user(session)

    response = client.post(
        "/v1/orders",
        headers=_auth_headers(user_id),
        json={
            "ticker": "AAPL",
            "side": "buy",
            "order_type": "market",
            "quantity": "1",
            "limit_price": "100",
        },
    )
    assert response.status_code == 400


def test_create_stop_loss_buy_returns_400(session: Session, client: TestClient) -> None:
    """stop_loss orders must be sell side."""
    _seed_market(session)
    user_id = _make_user(session)

    response = client.post(
        "/v1/orders",
        headers=_auth_headers(user_id),
        json={
            "ticker": "AAPL",
            "side": "buy",
            "order_type": "stop_loss",
            "quantity": "1",
            "limit_price": "100",
        },
    )
    assert response.status_code == 400


def test_create_order_ticker_upcased(session: Session, client: TestClient) -> None:
    _seed_market(session)
    user_id = _make_user(session)

    response = client.post(
        "/v1/orders",
        headers=_auth_headers(user_id),
        json={
            "ticker": "aapl",
            "side": "buy",
            "order_type": "limit",
            "quantity": "1",
            "limit_price": "140",
        },
    )
    assert response.status_code == 201
    assert response.json()["ticker"] == "AAPL"


# ---------------------------------------------------------------------------
# List orders
# ---------------------------------------------------------------------------


def test_list_orders_empty_for_new_user(session: Session, client: TestClient) -> None:
    user_id = _make_user(session)
    response = client.get("/v1/orders", headers=_auth_headers(user_id))
    assert response.status_code == 200
    assert response.json() == []


def test_list_orders_returns_created_order(session: Session, client: TestClient) -> None:
    _seed_market(session)
    user_id = _make_user(session)

    client.post(
        "/v1/orders",
        headers=_auth_headers(user_id),
        json={
            "ticker": "AAPL",
            "side": "buy",
            "order_type": "limit",
            "quantity": "1",
            "limit_price": "140",
        },
    )
    response = client.get("/v1/orders", headers=_auth_headers(user_id))
    assert response.status_code == 200
    orders = response.json()
    assert len(orders) == 1
    assert orders[0]["ticker"] == "AAPL"
    assert orders[0]["status"] == "pending"


def test_list_orders_status_filter_pending(session: Session, client: TestClient) -> None:
    _seed_market(session)
    user_id = _make_user(session)

    client.post(
        "/v1/orders",
        headers=_auth_headers(user_id),
        json={
            "ticker": "AAPL",
            "side": "buy",
            "order_type": "limit",
            "quantity": "1",
            "limit_price": "140",
        },
    )
    response = client.get("/v1/orders?status=pending", headers=_auth_headers(user_id))
    assert response.status_code == 200
    assert len(response.json()) == 1


def test_list_orders_status_filter_filled_empty(session: Session, client: TestClient) -> None:
    _seed_market(session)
    user_id = _make_user(session)

    client.post(
        "/v1/orders",
        headers=_auth_headers(user_id),
        json={
            "ticker": "AAPL",
            "side": "buy",
            "order_type": "limit",
            "quantity": "1",
            "limit_price": "140",
        },
    )
    response = client.get("/v1/orders?status=filled", headers=_auth_headers(user_id))
    assert response.status_code == 200
    assert response.json() == []


def test_list_orders_invalid_status_returns_400(session: Session, client: TestClient) -> None:
    user_id = _make_user(session)
    response = client.get("/v1/orders?status=invalid", headers=_auth_headers(user_id))
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# Cancel order
# ---------------------------------------------------------------------------


def test_cancel_pending_order(session: Session, client: TestClient) -> None:
    _seed_market(session)
    user_id = _make_user(session)

    create_resp = client.post(
        "/v1/orders",
        headers=_auth_headers(user_id),
        json={
            "ticker": "AAPL",
            "side": "buy",
            "order_type": "limit",
            "quantity": "1",
            "limit_price": "140",
        },
    )
    order_id = create_resp.json()["id"]

    delete_resp = client.delete(f"/v1/orders/{order_id}", headers=_auth_headers(user_id))
    assert delete_resp.status_code == 204

    orders = client.get("/v1/orders?status=cancelled", headers=_auth_headers(user_id)).json()
    assert any(o["id"] == order_id and o["status"] == "cancelled" for o in orders)


def test_cancel_nonexistent_order_returns_404(session: Session, client: TestClient) -> None:
    user_id = _make_user(session)
    response = client.delete("/v1/orders/9999", headers=_auth_headers(user_id))
    assert response.status_code == 404


def test_cancel_another_users_order_returns_404(session: Session, client: TestClient) -> None:
    _seed_market(session)
    user_id = _make_user(session)

    user2 = User(email="other@stockviz.dev", name="Other")
    session.add(user2)
    session.commit()
    session.refresh(user2)
    assert user2.id is not None

    create_resp = client.post(
        "/v1/orders",
        headers=_auth_headers(user_id),
        json={
            "ticker": "AAPL",
            "side": "buy",
            "order_type": "limit",
            "quantity": "1",
            "limit_price": "140",
        },
    )
    order_id = create_resp.json()["id"]

    response = client.delete(f"/v1/orders/{order_id}", headers=_auth_headers(user2.id))
    assert response.status_code == 404


def test_cancel_already_cancelled_order_returns_400(session: Session, client: TestClient) -> None:
    _seed_market(session)
    user_id = _make_user(session)

    create_resp = client.post(
        "/v1/orders",
        headers=_auth_headers(user_id),
        json={
            "ticker": "AAPL",
            "side": "buy",
            "order_type": "limit",
            "quantity": "1",
            "limit_price": "140",
        },
    )
    order_id = create_resp.json()["id"]

    client.delete(f"/v1/orders/{order_id}", headers=_auth_headers(user_id))
    response = client.delete(f"/v1/orders/{order_id}", headers=_auth_headers(user_id))
    assert response.status_code == 400
