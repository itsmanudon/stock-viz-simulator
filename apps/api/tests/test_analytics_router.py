"""HTTP-level tests for /v1/portfolio/analytics."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient
from jose import jwt as jose_jwt
from sqlmodel import Session, select

from stockviz.models import PortfolioSnapshot, PriceBar, Symbol, TradeSide, User
from stockviz.services.trading import (
    ensure_default_portfolio,
    execute_trade,
)
from stockviz.settings import get_settings

SECRET = get_settings().internal_api_token


def _auth_headers(user_id: int) -> dict[str, str]:
    token = jose_jwt.encode({"sub": str(user_id)}, SECRET, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


def _make_user(session: Session, email: str = "trader@stockviz.dev") -> int:
    user = User(email=email, name="Trader")
    session.add(user)
    session.commit()
    session.refresh(user)
    assert user.id is not None
    return user.id


def _seed_symbol_with_bar(
    session: Session,
    ticker: str,
    sector: str,
    close: Decimal = Decimal("100"),
) -> None:
    session.add(Symbol(ticker=ticker, name=ticker, sector=sector))
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


def test_analytics_requires_auth(client: TestClient) -> None:
    assert client.get("/v1/portfolio/analytics").status_code == 401


def test_analytics_zeroed_for_new_account(session: Session, client: TestClient) -> None:
    user_id = _make_user(session)
    response = client.get("/v1/portfolio/analytics", headers=_auth_headers(user_id))
    assert response.status_code == 200
    body = response.json()
    # No snapshots → time-series metrics absent.
    assert body["total_return_pct"] is None
    assert body["sharpe_ratio"] is None
    assert body["max_drawdown_pct"] is None
    assert body["history_days"] == 0
    # No positions → empty allocation / movers.
    assert body["sector_allocation"] == []
    assert body["top_gainers"] == []
    assert body["top_losers"] == []
    # Default risk-free rate exposed.
    assert body["risk_free_rate"] == 0.05


def _reset_snapshots(session: Session, user_id: int) -> None:
    """Drop the opening snapshot seeded by ``ensure_default_portfolio``.

    Portfolio creation writes a day-zero NAV row at the funded balance so the
    equity curve starts from inception. Tests that assert on a hand-built NAV
    series clear it first so they control the whole window.
    """
    for row in session.exec(
        select(PortfolioSnapshot).where(PortfolioSnapshot.user_id == user_id)
    ).all():
        session.delete(row)
    session.commit()


def test_analytics_computes_return_from_snapshots(session: Session, client: TestClient) -> None:
    user_id = _make_user(session)
    ensure_default_portfolio(session, user_id)
    _reset_snapshots(session, user_id)
    base_date = date(2025, 1, 1)
    # 100k -> 110k = +10% total return over the window.
    session.add_all(
        [
            PortfolioSnapshot(user_id=user_id, date=base_date, nav=Decimal(100_000)),
            PortfolioSnapshot(
                user_id=user_id, date=base_date + timedelta(days=30), nav=Decimal(110_000)
            ),
        ]
    )
    session.commit()

    response = client.get("/v1/portfolio/analytics", headers=_auth_headers(user_id))
    assert response.status_code == 200
    body = response.json()
    assert body["total_return_pct"] is not None
    assert abs(body["total_return_pct"] - 10.0) < 1e-6
    assert body["history_days"] == 30
    assert body["max_drawdown_pct"] == 0


def test_analytics_sector_allocation_and_top_movers(session: Session, client: TestClient) -> None:
    _seed_symbol_with_bar(session, "AAPL", "Technology", Decimal("150"))
    _seed_symbol_with_bar(session, "XOM", "Energy", Decimal("50"))
    user_id = _make_user(session)
    execute_trade(
        session,
        user_id=user_id,
        ticker="AAPL",
        side=TradeSide.BUY,
        quantity=Decimal(10),
    )
    execute_trade(
        session,
        user_id=user_id,
        ticker="XOM",
        side=TradeSide.BUY,
        quantity=Decimal(10),
    )
    # Bump AAPL's price 10% so it becomes a gainer; XOM stays flat.
    session.add(
        PriceBar(
            ticker="AAPL",
            ts=datetime(2025, 4, 11),
            interval="1d",
            open=Decimal(165),
            high=Decimal(165),
            low=Decimal(165),
            close=Decimal(165),
            volume=1,
            source="test",
        )
    )
    session.commit()

    response = client.get("/v1/portfolio/analytics", headers=_auth_headers(user_id))
    assert response.status_code == 200
    body = response.json()

    sectors = {a["sector"]: a["pct"] for a in body["sector_allocation"]}
    assert "Technology" in sectors
    assert "Energy" in sectors
    assert abs(sum(sectors.values()) - 100.0) < 0.01

    gainer_tickers = [m["ticker"] for m in body["top_gainers"]]
    assert "AAPL" in gainer_tickers


def test_analytics_custom_risk_free_rate(session: Session, client: TestClient) -> None:
    user_id = _make_user(session)
    response = client.get(
        "/v1/portfolio/analytics?risk_free_rate=0.02",
        headers=_auth_headers(user_id),
    )
    assert response.status_code == 200
    assert response.json()["risk_free_rate"] == 0.02
