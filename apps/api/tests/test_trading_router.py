"""HTTP-level tests for /v1/portfolio and /v1/trades.

Exercises the auth dependency end-to-end: missing token -> 401; bad token
-> 401; valid headers -> business path. Uses a known user.id since the
conftest fixture isolates each test on its own SQLite engine.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient
from jose import jwt as jose_jwt
from sqlalchemy import event
from sqlmodel import Session, select

from stockviz.auth import require_user_id
from stockviz.main import app
from stockviz.models import PortfolioSnapshot, Position, PriceBar, Symbol, Trade, TradeSide, User
from stockviz.models.market import FxRate
from stockviz.models.option import OptionsPosition, OptionType
from stockviz.models.order import OrderType, PendingOrder
from stockviz.services.trading import ensure_default_portfolio
from stockviz.settings import get_settings

SECRET = get_settings().internal_api_token


def _auth_headers(user_id: int) -> dict[str, str]:
    token = jose_jwt.encode({"sub": str(user_id)}, SECRET, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


def _seed_market(session: Session) -> None:
    session.add_all([Symbol(ticker="AAPL", name="Apple Inc.")])
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


def test_portfolio_requires_internal_token(client: TestClient) -> None:
    response = client.get("/v1/portfolio")
    assert response.status_code == 401


def test_portfolio_rejects_bad_token(client: TestClient) -> None:
    response = client.get("/v1/portfolio", headers={"Authorization": "Bearer not-a-valid-jwt"})
    assert response.status_code == 401


def test_portfolio_bootstraps_with_starting_cash(session: Session, client: TestClient) -> None:
    user_id = _make_user(session)
    response = client.get("/v1/portfolio", headers=_auth_headers(user_id))
    assert response.status_code == 200
    body = response.json()
    # First read auto-creates with the default starting cash.
    assert Decimal(body["cash_balance"]) == Decimal("100000.00")
    assert body["positions"] == []


def test_portfolio_overview_requires_auth(client: TestClient) -> None:
    assert client.get("/v1/portfolio/overview").status_code == 401
    assert (
        client.get(
            "/v1/portfolio/overview", headers={"Authorization": "Bearer invalid"}
        ).status_code
        == 401
    )


def test_portfolio_overview_reuses_one_valuation(session: Session, client: TestClient) -> None:
    _seed_market(session)
    user_id = _make_user(session)
    portfolio = ensure_default_portfolio(session, user_id)
    assert portfolio.id is not None
    session.add(
        Position(
            portfolio_id=portfolio.id, ticker="AAPL", quantity=Decimal(2), avg_cost=Decimal(100)
        )
    )
    session.commit()
    statements: list[str] = []

    def capture(_conn, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)

    engine = session.get_bind()
    event.listen(engine, "before_cursor_execute", capture)
    try:
        response = client.get(
            "/v1/portfolio/overview?risk_free_rate=0.02", headers=_auth_headers(user_id)
        )
    finally:
        event.remove(engine, "before_cursor_execute", capture)

    assert response.status_code == 200
    body = response.json()
    assert Decimal(body["portfolio"]["market_value"]) == Decimal(300)
    assert Decimal(body["portfolio"]["unrealized_pl"]) == Decimal(100)
    assert body["analytics"]["risk_free_rate"] == 0.02
    assert body["analytics"]["top_gainers"][0]["return_pct"] == 50.0
    assert sum("FROM positions JOIN symbols" in statement for statement in statements) == 1
    assert body["portfolio"] == client.get("/v1/portfolio", headers=_auth_headers(user_id)).json()
    assert (
        body["analytics"]
        == client.get(
            "/v1/portfolio/analytics?risk_free_rate=0.02", headers=_auth_headers(user_id)
        ).json()
    )


def test_portfolio_overview_is_private_and_fresh(session: Session, client: TestClient) -> None:
    first_id = _make_user(session)
    other = User(email="other@stockviz.dev", name="Other")
    session.add(other)
    session.commit()
    assert other.id is not None
    first = ensure_default_portfolio(session, first_id)
    second = ensure_default_portfolio(session, other.id)
    first.cash_balance = Decimal(123)
    second.cash_balance = Decimal(456)
    for snapshot in session.exec(select(PortfolioSnapshot)).all():
        session.add(
            PortfolioSnapshot(
                user_id=snapshot.user_id,
                date=snapshot.date + timedelta(days=1),
                nav=Decimal(110000 if snapshot.user_id == first_id else 200000),
            )
        )
    session.commit()
    for user_id, expected, return_pct in [(first_id, "123", 10), (other.id, "456", 100)]:
        response = client.get("/v1/portfolio/overview", headers=_auth_headers(user_id))
        assert response.status_code == 200
        assert Decimal(response.json()["portfolio"]["cash_balance"]) == Decimal(expected)
        assert abs(response.json()["analytics"]["total_return_pct"] - return_pct) < 0.000001
    first.cash_balance = Decimal(789)
    session.commit()
    response = client.get("/v1/portfolio/overview", headers=_auth_headers(first_id))
    assert Decimal(response.json()["portfolio"]["cash_balance"]) == Decimal(789)
    assert (
        client.get(
            "/v1/portfolio/overview?risk_free_rate=2", headers=_auth_headers(first_id)
        ).status_code
        == 422
    )


def test_portfolio_overview_preserves_fx_options_reservations_and_missing_prices(
    session: Session, client: TestClient
) -> None:
    _seed_market(session)
    user_id = _make_user(session)
    user = session.get(User, user_id)
    assert user is not None
    user.display_currency = "EUR"
    portfolio = ensure_default_portfolio(session, user_id)
    assert portfolio.id is not None
    session.add_all(
        [
            FxRate(currency="EUR", date=date(2025, 4, 10), usd_rate=Decimal(2)),
            Symbol(ticker="MISSING", name="No bars or FX", currency="JPY"),
            Position(
                portfolio_id=portfolio.id, ticker="AAPL", quantity=Decimal(2), avg_cost=Decimal(100)
            ),
            Position(
                portfolio_id=portfolio.id,
                ticker="MISSING",
                quantity=Decimal(2),
                avg_cost=Decimal(3),
            ),
            PendingOrder(
                portfolio_id=portfolio.id,
                ticker="AAPL",
                side=TradeSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal(2),
                limit_price=Decimal(100),
            ),
            PendingOrder(
                portfolio_id=portfolio.id,
                ticker="AAPL",
                side=TradeSide.SELL,
                order_type=OrderType.LIMIT,
                quantity=Decimal(1),
                limit_price=Decimal(200),
            ),
            OptionsPosition(
                user_id=user_id,
                portfolio_id=portfolio.id,
                ticker="AAPL",
                option_type=OptionType.CALL,
                strike=Decimal(140),
                expiry=date(2000, 1, 1),
                quantity=1,
                premium_paid=Decimal(100),
            ),
        ]
    )
    session.commit()
    response = client.get("/v1/portfolio/overview", headers=_auth_headers(user_id))
    assert response.status_code == 200
    overview = response.json()
    body = overview["portfolio"]
    assert body["display_currency"] == "EUR"
    for field, expected in {
        "cash_balance": "50000",
        "reserved_cash": "100",
        "available_cash": "49900",
        "market_value": "150",
        "options_market_value": "500",
        "total_value": "50650",
        "total_cost_basis": "106",
        "unrealized_pl": "44",
    }.items():
        assert Decimal(body[field]) == Decimal(expected), field
    positions = {position["ticker"]: position for position in body["positions"]}
    assert Decimal(positions["AAPL"]["reserved_quantity"]) == 1
    assert Decimal(positions["AAPL"]["available_quantity"]) == 1
    assert positions["MISSING"]["last_close"] is None
    assert Decimal(positions["MISSING"]["unrealized_pl"]) == -6
    assert Decimal(body["option_positions"][0]["unrealized_pl"]) == 450
    assert overview["analytics"]["display_currency"] == "EUR"
    assert body == client.get("/v1/portfolio", headers=_auth_headers(user_id)).json()
    assert (
        overview["analytics"]
        == client.get("/v1/portfolio/analytics", headers=_auth_headers(user_id)).json()
    )


def test_trade_buy_then_portfolio_reflects(session: Session, client: TestClient) -> None:
    _seed_market(session)
    user_id = _make_user(session)

    # Place a 5-share buy.
    response = client.post(
        "/v1/trades",
        headers=_auth_headers(user_id),
        json={"ticker": "AAPL", "side": "buy", "quantity": "5"},
    )
    assert response.status_code == 201
    trade = response.json()
    assert trade["price"] == "150.000000"
    assert trade["side"] == "buy"

    # Portfolio reflects the buy.
    response = client.get("/v1/portfolio", headers=_auth_headers(user_id))
    body = response.json()
    assert Decimal(body["cash_balance"]) == Decimal("100000.00") - Decimal("750.00")
    assert len(body["positions"]) == 1
    assert body["positions"][0]["ticker"] == "AAPL"
    assert Decimal(body["positions"][0]["quantity"]) == Decimal(5)

    # /v1/trades returns the history.
    response = client.get("/v1/trades", headers=_auth_headers(user_id))
    body = response.json()
    assert len(body) == 1
    assert body[0]["ticker"] == "AAPL"
    assert "execution" not in body[0]
    assert "profile_name" not in body[0]

    trade_id = trade["id"]
    response = client.get(f"/v1/trades/{trade_id}/execution", headers=_auth_headers(user_id))
    assert response.status_code == 200
    provenance = response.json()
    assert provenance["profile_name"] == "legacy_close"
    assert provenance["model_version"] == "v1"
    assert provenance["fill_price"] == "150.000000"
    assert provenance["reference_price"] == "150.000000"
    assert provenance["market_interval"] == "1d"
    assert provenance["order_type"] == "market"
    assert provenance["assumptions"]
    assert provenance["evaluated_at"].endswith("+00:00") or provenance["evaluated_at"].endswith("Z")


def test_insufficient_cash_returns_422(session: Session, client: TestClient) -> None:
    _seed_market(session)
    user_id = _make_user(session)
    response = client.post(
        "/v1/trades",
        headers=_auth_headers(user_id),
        json={"ticker": "AAPL", "side": "buy", "quantity": "10000"},
    )
    assert response.status_code == 422


def test_unknown_symbol_returns_404(session: Session, client: TestClient) -> None:
    user_id = _make_user(session)
    response = client.post(
        "/v1/trades",
        headers=_auth_headers(user_id),
        json={"ticker": "NOPE", "side": "buy", "quantity": "1"},
    )
    assert response.status_code == 404


def test_execution_404_for_historical_trade_without_provenance(
    session: Session, client: TestClient
) -> None:

    _seed_market(session)
    user_id = _make_user(session)
    portfolio = ensure_default_portfolio(session, user_id)
    assert portfolio.id is not None
    trade = Trade(
        portfolio_id=portfolio.id,
        ticker="AAPL",
        side=TradeSide.BUY,
        quantity=Decimal(1),
        price=Decimal("150"),
        fx_rate=Decimal(1),
    )
    session.add(trade)
    session.commit()
    session.refresh(trade)

    history = client.get("/v1/trades", headers=_auth_headers(user_id))
    assert history.status_code == 200
    assert len(history.json()) == 1

    response = client.get(f"/v1/trades/{trade.id}/execution", headers=_auth_headers(user_id))
    assert response.status_code == 404
    assert "provenance" in response.json()["detail"].lower()


def test_execution_404_for_missing_trade(session: Session, client: TestClient) -> None:
    user_id = _make_user(session)
    response = client.get("/v1/trades/999999/execution", headers=_auth_headers(user_id))
    assert response.status_code == 404


def test_auth_dependency_override_works(session: Session, client: TestClient) -> None:
    """The auth headers are the production path; ensure the dep itself is overridable
    for tests / scripts that want to inject a user id directly."""

    user_id = _make_user(session)
    app.dependency_overrides[require_user_id] = lambda: user_id
    try:
        response = client.get("/v1/portfolio")  # no headers
        assert response.status_code == 200
    finally:
        app.dependency_overrides.pop(require_user_id, None)
