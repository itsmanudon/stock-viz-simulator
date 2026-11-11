"""GET /v1/options/quote prices an open the way the open charges it (audit LG-7)."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient
from jose import jwt as jose_jwt
from sqlmodel import Session

from stockviz._time import utcnow
from stockviz.models import PriceBar, Symbol, User
from stockviz.settings import get_settings

SECRET = get_settings().internal_api_token


def _seed(session: Session) -> int:
    session.add_all(
        [
            Symbol(ticker="AAPL", name="Apple"),
            Symbol(ticker="SAP.DE", name="SAP", currency="EUR"),
            Symbol(ticker="NOBARS", name="No bars"),
        ]
    )
    user = User(email="quote@stockviz.dev", name="Quote")
    session.add(user)
    session.commit()
    for day in range(40):
        close = Decimal(100 + day % 5)
        session.add(
            PriceBar(
                ticker="AAPL",
                ts=datetime(2026, 9, 1) + timedelta(days=day),
                interval="1d",
                open=close,
                high=close,
                low=close,
                close=close,
                volume=1_000,
                source="test",
            )
        )
    session.commit()
    assert user.id is not None
    return user.id


def _params(**extra: str) -> dict[str, str]:
    return {
        "ticker": "AAPL",
        "option_type": "call",
        "strike": "100",
        "expiry": (utcnow().date() + timedelta(days=60)).isoformat(),
        "quantity": "2",
        **extra,
    }


def test_quote_matches_what_the_open_charges(session: Session, client: TestClient) -> None:
    user_id = _seed(session)

    quote = client.get("/v1/options/quote", params=_params())
    assert quote.status_code == 200, quote.text
    body = quote.json()
    assert Decimal(body["spot"]) == Decimal(104)  # day 39: 100 + 39 % 5
    assert body["spot_at"].startswith("2026-10-10")
    assert body["contract_size"] == 100
    assert body["volatility"] > 0
    assert Decimal(body["premium"]) > 0

    token = jose_jwt.encode({"sub": str(user_id)}, SECRET, algorithm="HS256")
    opened = client.post(
        "/v1/options/trade",
        json={"action": "open", **_params(), "quantity": 2},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert opened.status_code == 201, opened.text
    assert Decimal(opened.json()["position"]["premium_paid"]) == Decimal(body["premium"])


def test_quote_needs_no_sign_in_and_refuses_what_the_open_refuses(
    session: Session, client: TestClient
) -> None:
    _seed(session)

    assert client.get("/v1/options/quote", params=_params(ticker="ZZZZ")).status_code == 404
    assert client.get("/v1/options/quote", params=_params(ticker="SAP.DE")).status_code == 400
    assert client.get("/v1/options/quote", params=_params(ticker="NOBARS")).status_code == 422
    past = (utcnow().date() - timedelta(days=1)).isoformat()
    assert client.get("/v1/options/quote", params=_params(expiry=past)).status_code == 400
    assert client.get("/v1/options/quote", params=_params(strike="0")).status_code == 422


def test_quote_without_a_strike_prices_at_the_money(session: Session, client: TestClient) -> None:
    _seed(session)
    params = _params()
    del params["strike"]

    body = client.get("/v1/options/quote", params=params).json()

    assert Decimal(body["strike"]) == Decimal("104.00")
