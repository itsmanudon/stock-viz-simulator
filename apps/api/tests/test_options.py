"""Tests for options pricing, the trade lifecycle, expiry settlement, and the
/v1/options endpoints."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from jose import jwt as jose_jwt
from sqlmodel import Session, select

from stockviz.models import (
    OptionsPosition,
    OptionStatus,
    OptionType,
    Position,
    PriceBar,
    Symbol,
    User,
)
from stockviz.services.options import (
    InsufficientCashForOption,
    InvalidExpiry,
    OptionSymbolNotFound,
    black_scholes,
    close_option,
    historical_volatility,
    open_option,
    settle_expired_options,
)
from stockviz.services.trading import DEFAULT_STARTING_CASH, ensure_default_portfolio
from stockviz.settings import get_settings

SECRET = get_settings().internal_api_token
_EPOCH = datetime(2024, 1, 1)


def _auth_headers(user_id: int) -> dict[str, str]:
    token = jose_jwt.encode({"sub": str(user_id)}, SECRET, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


def _make_user(session: Session, email: str = "opt@stockviz.dev") -> int:
    user = User(email=email, name="Optioneer")
    session.add(user)
    session.commit()
    session.refresh(user)
    assert user.id is not None
    return user.id


def _seed_symbol(session: Session, ticker: str = "AAPL") -> None:
    if session.get(Symbol, ticker) is None:
        session.add(Symbol(ticker=ticker, name=f"{ticker} Inc."))
        session.commit()


def _seed_bars(session: Session, prices: Sequence[float], ticker: str = "AAPL") -> None:
    """Seed daily bars; the last price becomes the spot."""
    _seed_symbol(session, ticker)
    for i, p in enumerate(prices):
        price = Decimal(str(p))
        session.add(
            PriceBar(
                ticker=ticker,
                ts=_EPOCH + timedelta(days=i),
                interval="1d",
                open=price,
                high=price,
                low=price,
                close=price,
                volume=1_000_000,
                source="test",
            )
        )
    session.commit()


# ---------------------------------------------------------------------------
# Black-Scholes pricing
# ---------------------------------------------------------------------------


def test_black_scholes_matches_textbook_values() -> None:
    # Canonical example: S=100, K=100, T=1, r=5%, sigma=20%.
    call = black_scholes(
        spot=100,
        strike=100,
        time_to_expiry_years=1,
        volatility=0.2,
        risk_free_rate=0.05,
        option_type="call",
    )
    put = black_scholes(
        spot=100,
        strike=100,
        time_to_expiry_years=1,
        volatility=0.2,
        risk_free_rate=0.05,
        option_type="put",
    )
    assert call.value == pytest.approx(10.4506, abs=0.01)
    assert put.value == pytest.approx(5.5735, abs=0.01)
    # Put-call parity: C - P == S - K*e^(-rT).
    import math

    assert (call.value - put.value) == pytest.approx(100 - 100 * math.exp(-0.05), abs=0.01)


def test_black_scholes_call_delta_in_range() -> None:
    call = black_scholes(
        spot=100,
        strike=100,
        time_to_expiry_years=1,
        volatility=0.2,
        risk_free_rate=0.05,
        option_type="call",
    )
    assert 0.0 < call.delta < 1.0
    assert call.vega > 0.0


def test_black_scholes_degenerates_to_intrinsic_at_expiry() -> None:
    # T=0 -> value collapses to intrinsic, greeks zero.
    itm_call = black_scholes(
        spot=120,
        strike=100,
        time_to_expiry_years=0,
        volatility=0.2,
        risk_free_rate=0.05,
        option_type="call",
    )
    assert itm_call.value == pytest.approx(20.0, abs=0.01)
    otm_call = black_scholes(
        spot=80,
        strike=100,
        time_to_expiry_years=0,
        volatility=0.2,
        risk_free_rate=0.05,
        option_type="call",
    )
    assert otm_call.value == pytest.approx(0.0, abs=0.01)


def test_historical_volatility_positive_for_varying_series() -> None:
    closes = [Decimal(str(100 + (i % 5))) for i in range(40)]
    assert historical_volatility(closes) > 0.0


def test_historical_volatility_zero_for_flat_series() -> None:
    assert historical_volatility([Decimal(100)] * 40) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Open / close lifecycle
# ---------------------------------------------------------------------------


def test_open_option_debits_premium_and_creates_position(session: Session) -> None:
    _seed_bars(session, [100 + (i % 7) for i in range(40)])
    user_id = _make_user(session)
    portfolio = ensure_default_portfolio(session, user_id)

    result = open_option(
        session,
        user_id=user_id,
        ticker="AAPL",
        option_type=OptionType.CALL,
        strike=Decimal(100),
        expiry=date.today() + timedelta(days=30),
        quantity=2,
    )

    assert result.position.status == OptionStatus.OPEN
    assert result.position.quantity == 2
    assert result.position.premium_paid > 0
    assert result.cash_delta == -result.position.premium_paid

    session.refresh(portfolio)
    assert portfolio.cash_balance == DEFAULT_STARTING_CASH - result.position.premium_paid


def test_open_option_premium_equals_black_scholes(session: Session) -> None:
    """The stored premium must equal BS value * 100 * contracts."""
    closes = [100 + (i % 7) for i in range(40)]
    _seed_bars(session, closes)
    user_id = _make_user(session)

    expiry = date.today() + timedelta(days=60)
    result = open_option(
        session,
        user_id=user_id,
        ticker="AAPL",
        option_type=OptionType.CALL,
        strike=Decimal(100),
        expiry=expiry,
        quantity=1,
    )

    vol = historical_volatility([Decimal(str(c)) for c in closes])
    spot = float(closes[-1])
    expected = black_scholes(
        spot=spot,
        strike=100.0,
        time_to_expiry_years=(expiry - date.today()).days / 365.0,
        volatility=vol,
        risk_free_rate=0.05,
        option_type="call",
    )
    expected_premium = Decimal(str(expected.value)) * 100 * 1
    assert float(result.position.premium_paid) == pytest.approx(float(expected_premium), abs=0.01)


def test_open_option_unknown_ticker_raises(session: Session) -> None:
    user_id = _make_user(session)
    with pytest.raises(OptionSymbolNotFound):
        open_option(
            session,
            user_id=user_id,
            ticker="NOPE",
            option_type=OptionType.CALL,
            strike=Decimal(100),
            expiry=date.today() + timedelta(days=30),
            quantity=1,
        )


def test_open_option_past_expiry_raises(session: Session) -> None:
    _seed_bars(session, [100.0] * 40)
    user_id = _make_user(session)
    with pytest.raises(InvalidExpiry):
        open_option(
            session,
            user_id=user_id,
            ticker="AAPL",
            option_type=OptionType.CALL,
            strike=Decimal(100),
            expiry=date.today() - timedelta(days=1),
            quantity=1,
        )


def test_open_option_insufficient_cash_raises(session: Session) -> None:
    _seed_bars(session, [100 + (i % 7) for i in range(40)])
    user_id = _make_user(session)
    with pytest.raises(InsufficientCashForOption):
        # 100000 contracts of a ~$x option blows past the $100k starting cash.
        open_option(
            session,
            user_id=user_id,
            ticker="AAPL",
            option_type=OptionType.CALL,
            strike=Decimal(100),
            expiry=date.today() + timedelta(days=30),
            quantity=100_000,
        )


def test_close_option_credits_cash_and_marks_closed(session: Session) -> None:
    _seed_bars(session, [100 + (i % 7) for i in range(40)])
    user_id = _make_user(session)
    portfolio = ensure_default_portfolio(session, user_id)

    opened = open_option(
        session,
        user_id=user_id,
        ticker="AAPL",
        option_type=OptionType.CALL,
        strike=Decimal(100),
        expiry=date.today() + timedelta(days=30),
        quantity=1,
    )
    session.refresh(portfolio)
    cash_after_open = portfolio.cash_balance

    closed = close_option(session, user_id=user_id, option_id=opened.position.id)  # type: ignore[arg-type]
    assert closed.position.status == OptionStatus.CLOSED
    assert closed.cash_delta >= 0

    session.refresh(portfolio)
    assert portfolio.cash_balance == cash_after_open + closed.cash_delta


# ---------------------------------------------------------------------------
# Expiry settlement
# ---------------------------------------------------------------------------


def _open_raw_position(
    session: Session,
    *,
    user_id: int,
    portfolio_id: int,
    option_type: OptionType,
    strike: Decimal,
    expiry: date,
    quantity: int = 1,
) -> OptionsPosition:
    """Create an OptionsPosition row directly (bypasses the future-expiry check)."""
    pos = OptionsPosition(
        user_id=user_id,
        portfolio_id=portfolio_id,
        ticker="AAPL",
        option_type=option_type,
        strike=strike,
        expiry=expiry,
        quantity=quantity,
        premium_paid=Decimal("500.00"),
        status=OptionStatus.OPEN,
    )
    session.add(pos)
    session.commit()
    session.refresh(pos)
    return pos


def test_settle_itm_call_exercises_into_equity(session: Session) -> None:
    _seed_bars(session, [150.0])  # spot = 150
    user_id = _make_user(session)
    portfolio = ensure_default_portfolio(session, user_id)
    pos = _open_raw_position(
        session,
        user_id=user_id,
        portfolio_id=portfolio.id,  # type: ignore[arg-type]
        option_type=OptionType.CALL,
        strike=Decimal(100),
        expiry=date.today() - timedelta(days=1),
    )

    settled = settle_expired_options(session, settle_date=date.today())
    assert settled == 1

    session.refresh(pos)
    assert pos.status == OptionStatus.EXERCISED

    # 1 contract -> 100 shares bought at strike 100 -> $10,000 debited.
    equity = session.exec(
        select(Position).where(Position.portfolio_id == portfolio.id, Position.ticker == "AAPL")
    ).first()
    assert equity is not None
    assert equity.quantity == Decimal(100)
    assert equity.avg_cost == Decimal(100)
    session.refresh(portfolio)
    assert portfolio.cash_balance == DEFAULT_STARTING_CASH - Decimal(10_000)


def test_settle_otm_call_expires_worthless(session: Session) -> None:
    _seed_bars(session, [80.0])  # spot = 80, below strike 100
    user_id = _make_user(session)
    portfolio = ensure_default_portfolio(session, user_id)
    pos = _open_raw_position(
        session,
        user_id=user_id,
        portfolio_id=portfolio.id,  # type: ignore[arg-type]
        option_type=OptionType.CALL,
        strike=Decimal(100),
        expiry=date.today() - timedelta(days=1),
    )

    settle_expired_options(session, settle_date=date.today())
    session.refresh(pos)
    assert pos.status == OptionStatus.EXPIRED

    # No equity position, no cash movement.
    equity = session.exec(select(Position).where(Position.portfolio_id == portfolio.id)).first()
    assert equity is None
    session.refresh(portfolio)
    assert portfolio.cash_balance == DEFAULT_STARTING_CASH


def test_settle_itm_put_sells_held_shares(session: Session) -> None:
    _seed_bars(session, [80.0])  # spot = 80, below strike 100 -> put ITM
    user_id = _make_user(session)
    portfolio = ensure_default_portfolio(session, user_id)
    # The portfolio already holds 100 shares.
    assert portfolio.id is not None
    session.add(
        Position(
            portfolio_id=portfolio.id, ticker="AAPL", quantity=Decimal(100), avg_cost=Decimal(90)
        )
    )
    session.commit()
    pos = _open_raw_position(
        session,
        user_id=user_id,
        portfolio_id=portfolio.id,  # type: ignore[arg-type]
        option_type=OptionType.PUT,
        strike=Decimal(100),
        expiry=date.today() - timedelta(days=1),
    )

    settle_expired_options(session, settle_date=date.today())
    session.refresh(pos)
    assert pos.status == OptionStatus.EXERCISED

    # 100 shares sold at strike 100 -> +$10,000, position fully closed.
    equity = session.exec(select(Position).where(Position.portfolio_id == portfolio.id)).first()
    assert equity is None
    session.refresh(portfolio)
    assert portfolio.cash_balance == DEFAULT_STARTING_CASH + Decimal(10_000)


def test_settle_itm_put_cash_settles_without_shares(session: Session) -> None:
    _seed_bars(session, [80.0])  # spot = 80, strike 100 -> intrinsic 20/share
    user_id = _make_user(session)
    portfolio = ensure_default_portfolio(session, user_id)
    pos = _open_raw_position(
        session,
        user_id=user_id,
        portfolio_id=portfolio.id,  # type: ignore[arg-type]
        option_type=OptionType.PUT,
        strike=Decimal(100),
        expiry=date.today() - timedelta(days=1),
    )

    settle_expired_options(session, settle_date=date.today())
    session.refresh(pos)
    assert pos.status == OptionStatus.EXERCISED

    # No shares to deliver -> cash-settle intrinsic (100-80)*100 = $2,000.
    session.refresh(portfolio)
    assert portfolio.cash_balance == DEFAULT_STARTING_CASH + Decimal(2_000)


def test_settle_is_idempotent(session: Session) -> None:
    _seed_bars(session, [150.0])
    user_id = _make_user(session)
    portfolio = ensure_default_portfolio(session, user_id)
    _open_raw_position(
        session,
        user_id=user_id,
        portfolio_id=portfolio.id,  # type: ignore[arg-type]
        option_type=OptionType.CALL,
        strike=Decimal(100),
        expiry=date.today() - timedelta(days=1),
    )
    assert settle_expired_options(session, settle_date=date.today()) == 1
    # Second run finds nothing still OPEN.
    assert settle_expired_options(session, settle_date=date.today()) == 0


# ---------------------------------------------------------------------------
# HTTP endpoints
# ---------------------------------------------------------------------------


def test_options_endpoints_require_auth(client: TestClient) -> None:
    assert client.get("/v1/options/positions").status_code == 401
    assert client.post("/v1/options/trade", json={"action": "open"}).status_code == 401


def test_trade_open_then_list_positions(session: Session, client: TestClient) -> None:
    _seed_bars(session, [100 + (i % 7) for i in range(40)])
    user_id = _make_user(session)
    headers = _auth_headers(user_id)

    expiry = (date.today() + timedelta(days=45)).isoformat()
    resp = client.post(
        "/v1/options/trade",
        headers=headers,
        json={
            "action": "open",
            "ticker": "aapl",
            "option_type": "call",
            "strike": "100",
            "expiry": expiry,
            "quantity": 1,
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["position"]["ticker"] == "AAPL"
    assert body["position"]["status"] == "open"
    assert Decimal(body["cash_delta"]) < 0

    listed = client.get("/v1/options/positions", headers=headers).json()
    assert len(listed) == 1
    assert listed[0]["option_type"] == "call"
    assert "greeks" in listed[0]


def test_trade_open_missing_fields_returns_400(session: Session, client: TestClient) -> None:
    user_id = _make_user(session)
    resp = client.post(
        "/v1/options/trade",
        headers=_auth_headers(user_id),
        json={"action": "open", "ticker": "AAPL"},
    )
    assert resp.status_code == 400


def test_trade_open_unknown_ticker_returns_404(session: Session, client: TestClient) -> None:
    user_id = _make_user(session)
    resp = client.post(
        "/v1/options/trade",
        headers=_auth_headers(user_id),
        json={
            "action": "open",
            "ticker": "NOPE",
            "option_type": "put",
            "strike": "100",
            "expiry": (date.today() + timedelta(days=30)).isoformat(),
            "quantity": 1,
        },
    )
    assert resp.status_code == 404


def test_trade_close_round_trip(session: Session, client: TestClient) -> None:
    _seed_bars(session, [100 + (i % 7) for i in range(40)])
    user_id = _make_user(session)
    headers = _auth_headers(user_id)

    opened = client.post(
        "/v1/options/trade",
        headers=headers,
        json={
            "action": "open",
            "ticker": "AAPL",
            "option_type": "call",
            "strike": "100",
            "expiry": (date.today() + timedelta(days=45)).isoformat(),
            "quantity": 1,
        },
    ).json()
    option_id = opened["position"]["id"]

    resp = client.post(
        "/v1/options/trade",
        headers=headers,
        json={"action": "close", "option_id": option_id},
    )
    assert resp.status_code == 201
    assert resp.json()["position"]["status"] == "closed"

    # Closing removes it from the open-positions list.
    assert client.get("/v1/options/positions", headers=headers).json() == []
