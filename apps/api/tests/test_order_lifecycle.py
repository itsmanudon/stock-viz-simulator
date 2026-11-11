"""Order lifecycle fixes: bounds (LG-9), per-order commits (LG-4), placement
time (LG-5) and expiry (LG-6)."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from jose import jwt as jose_jwt
from sqlmodel import Session

from stockviz.models import PendingOrder, PriceBar, Symbol, User
from stockviz.models.order import OrderStatus, OrderType
from stockviz.models.portfolio import TradeSide
from stockviz.services.trading import available_cash, ensure_default_portfolio
from stockviz.services.trading import orders as orders_module
from stockviz.services.trading.orders import settle_pending_orders
from stockviz.settings import get_settings

# A past week: the execution kernel ignores bars dated after the real clock.
WEDNESDAY = datetime(2026, 11, 4)
THURSDAY = datetime(2026, 11, 5)


def _headers(user_id: int) -> dict[str, str]:
    token = jose_jwt.encode(
        {"sub": str(user_id)}, get_settings().internal_api_token, algorithm="HS256"
    )
    return {"Authorization": f"Bearer {token}"}


def _setup(session: Session, *bars: tuple[datetime, str]) -> tuple[int, int]:
    session.add(Symbol(ticker="AAPL", name="Apple"))
    user = User(email="life@stockviz.dev", name="Life")
    session.add(user)
    session.commit()
    for ts, close in bars:
        value = Decimal(close)
        session.add(
            PriceBar(
                ticker="AAPL",
                ts=ts,
                interval="1d",
                open=value,
                high=value,
                low=value,
                close=value,
                volume=1,
                source="test",
            )
        )
    session.commit()
    assert user.id is not None
    portfolio = ensure_default_portfolio(session, user.id)
    assert portfolio.id is not None
    return user.id, portfolio.id


def _order(
    session: Session, portfolio_id: int, *, created_at: datetime, limit: str = "150"
) -> PendingOrder:
    order = PendingOrder(
        portfolio_id=portfolio_id,
        ticker="AAPL",
        side=TradeSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal(1),
        limit_price=Decimal(limit),
        created_at=created_at,
    )
    session.add(order)
    session.commit()
    session.refresh(order)
    return order


# --- LG-9 -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("quantity", "fragment"),
    [("NaN", "finite number"), ("0", "must be positive"), ("1.1234567", "6 decimal places")],
)
def test_a_market_order_rejects_bad_quantities(
    session: Session, client: TestClient, quantity: str, fragment: str
) -> None:
    user_id, _ = _setup(session, (WEDNESDAY, "100"))
    response = client.post(
        "/v1/trades",
        headers=_headers(user_id),
        json={"ticker": "AAPL", "side": "buy", "quantity": quantity},
    )
    assert response.status_code == 422
    assert fragment in response.text


def test_a_pending_order_rejects_nan_with_a_400_not_a_500(
    session: Session, client: TestClient
) -> None:
    user_id, _ = _setup(session, (WEDNESDAY, "100"))
    response = client.post(
        "/v1/orders",
        headers=_headers(user_id),
        json={
            "ticker": "AAPL",
            "side": "buy",
            "order_type": "limit",
            "quantity": "NaN",
            "limit_price": "150",
        },
    )
    assert response.status_code == 400
    assert "must be a number" in response.json()["detail"]


def test_option_inputs_are_bounded(session: Session, client: TestClient) -> None:
    user_id, _ = _setup(session, (WEDNESDAY, "100"))
    base = {
        "action": "open",
        "ticker": "AAPL",
        "option_type": "call",
        "strike": "100",
        "quantity": 1,
    }
    far = (datetime.now() + timedelta(days=365 * 10)).date().isoformat()
    for patch in ({"quantity": 0}, {"quantity": 5000}, {"strike": "NaN"}, {"expiry": far}):
        body = {**base, "expiry": "2027-01-15", **patch}
        response = client.post("/v1/options/trade", headers=_headers(user_id), json=body)
        assert response.status_code == 422, patch


# --- LG-4 -----------------------------------------------------------------


def test_one_failing_order_does_not_undo_the_others(session: Session, monkeypatch) -> None:
    _, portfolio_id = _setup(session, (WEDNESDAY, "100"))
    first = _order(session, portfolio_id, created_at=WEDNESDAY - timedelta(days=1))
    second = _order(session, portfolio_id, created_at=WEDNESDAY - timedelta(days=1))
    real_fill = orders_module._fill

    def flaky(sess, order, *args, **kwargs):
        if order.id == first.id:
            raise RuntimeError("boom")
        return real_fill(sess, order, *args, **kwargs)

    monkeypatch.setattr(orders_module, "_fill", flaky)
    assert settle_pending_orders(session) == 1
    session.refresh(first)
    session.refresh(second)
    assert (first.status, second.status) == (OrderStatus.PENDING, OrderStatus.FILLED)


# --- LG-5 -----------------------------------------------------------------


@pytest.mark.placement_guard
def test_an_order_placed_after_the_close_waits_for_the_next_session(session: Session) -> None:
    """Placed Wednesday 18:00 New York (23:00 UTC): Wednesday's close was already known."""
    _, portfolio_id = _setup(session, (WEDNESDAY, "100"))
    order = _order(session, portfolio_id, created_at=datetime(2026, 11, 4, 23, 0))
    assert settle_pending_orders(session) == 0

    session.add(
        PriceBar(
            ticker="AAPL",
            ts=THURSDAY,
            interval="1d",
            open=Decimal(100),
            high=Decimal(100),
            low=Decimal(100),
            close=Decimal(100),
            volume=1,
            source="test",
        )
    )
    session.commit()
    assert settle_pending_orders(session) == 1
    session.refresh(order)
    assert order.status == OrderStatus.FILLED


@pytest.mark.placement_guard
def test_an_order_placed_during_the_session_fills_on_its_close(session: Session) -> None:
    """Placed Wednesday 11:00 New York: Wednesday's close was not known yet."""
    _, portfolio_id = _setup(session, (WEDNESDAY, "100"))
    _order(session, portfolio_id, created_at=datetime(2026, 11, 4, 16, 0))
    assert settle_pending_orders(session) == 1


# --- LG-6 -----------------------------------------------------------------


def test_an_old_order_expires_and_frees_its_reservation(session: Session) -> None:
    _, portfolio_id = _setup(session, (WEDNESDAY, "100"))
    order = _order(
        session, portfolio_id, created_at=datetime.now() - timedelta(days=31), limit="50"
    )
    portfolio = session.get(orders_module.Portfolio, portfolio_id)
    assert portfolio is not None
    before = available_cash(session, portfolio)

    assert settle_pending_orders(session) == 0
    session.refresh(order)
    assert order.status == OrderStatus.EXPIRED
    assert order.cancel_reason is not None and "Expired after 30 days" in order.cancel_reason
    assert available_cash(session, portfolio) == before + Decimal(50)
