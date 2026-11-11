"""A valuation says what it could not price, and such a NAV is not stored (LG-13).

A holding without a close counted as 0, an unpriceable option as 0 and an
amount without an FX rate as if it were already in the display currency, all
silently, and the nightly snapshot saved the result as a real NAV.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient
from jose import jwt as jose_jwt
from sqlmodel import Session, select

from stockviz._time import utcnow
from stockviz.models import PortfolioSnapshot, Position, PriceBar, Symbol, User
from stockviz.models.option import OptionsPosition, OptionStatus, OptionType
from stockviz.services.trading import (
    compute_portfolio,
    ensure_default_portfolio,
    snapshot_user_navs,
)
from stockviz.settings import get_settings

SECRET = get_settings().internal_api_token
SESSION = date(2026, 11, 6)


def _headers(user_id: int) -> dict[str, str]:
    token = jose_jwt.encode({"sub": str(user_id)}, SECRET, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


def _book(session: Session, *holdings: tuple[str, str, bool]) -> tuple[int, int]:
    """A user holding 10 of each (ticker, currency, priced); returns ids."""
    user = User(email="valuation@stockviz.dev", name="Valuation")
    session.add(user)
    for ticker, currency, _priced in holdings:
        session.add(Symbol(ticker=ticker, name=ticker, currency=currency))
    session.commit()
    assert user.id is not None
    portfolio = ensure_default_portfolio(session, user.id)
    assert portfolio.id is not None
    for ticker, _currency, priced in holdings:
        session.add(
            Position(
                portfolio_id=portfolio.id, ticker=ticker, quantity=Decimal(10), avg_cost=Decimal(90)
            )
        )
        if priced:
            close = Decimal(100)
            session.add(
                PriceBar(
                    ticker=ticker,
                    ts=datetime(2026, 11, 6),
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
    return user.id, portfolio.id


def _codes(session: Session, user_id: int) -> list[tuple[str, str]]:
    portfolio = ensure_default_portfolio(session, user_id)
    return [(w.code, w.subject) for w in compute_portfolio(session, portfolio).warnings]


def test_a_fully_priced_book_has_no_warnings(session: Session) -> None:
    user_id, _ = _book(session, ("AAPL", "USD", True))

    assert _codes(session, user_id) == []


def test_a_holding_without_a_close_is_reported(session: Session, client: TestClient) -> None:
    user_id, _ = _book(session, ("AAPL", "USD", True), ("MSFT", "USD", False))

    assert _codes(session, user_id) == [("no_close", "MSFT")]
    body = client.get("/v1/portfolio", headers=_headers(user_id)).json()
    assert [w["code"] for w in body["valuation_warnings"]] == ["no_close"]
    assert "MSFT" in body["valuation_warnings"][0]["message"]


def test_a_currency_without_a_rate_is_reported_once(session: Session) -> None:
    user_id, _ = _book(session, ("7203.T", "JPY", True), ("6758.T", "JPY", True))

    assert _codes(session, user_id) == [("no_fx_rate", "JPY")]


def test_an_option_without_a_price_is_reported(session: Session) -> None:
    user_id, portfolio_id = _book(session, ("AAPL", "USD", True))
    session.add(Symbol(ticker="NVDA", name="NVDA"))
    session.commit()
    session.add(
        OptionsPosition(
            user_id=user_id,
            portfolio_id=portfolio_id,
            ticker="NVDA",
            option_type=OptionType.CALL,
            strike=Decimal(100),
            expiry=utcnow().date() + timedelta(days=30),
            quantity=1,
            premium_paid=Decimal(300),
            status=OptionStatus.OPEN,
        )
    )
    session.commit()

    assert _codes(session, user_id) == [("no_option_price", "NVDA")]


def test_an_incomplete_valuation_keeps_the_last_good_snapshot(session: Session) -> None:
    user_id, _ = _book(session, ("AAPL", "USD", True), ("MSFT", "USD", False))
    session.add(PortfolioSnapshot(user_id=user_id, date=date(2026, 11, 5), nav=Decimal(100_500)))
    session.commit()

    written = snapshot_user_navs(session, snapshot_date=SESSION)

    assert written == 0
    days = {s.date for s in session.exec(select(PortfolioSnapshot)).all()}
    assert SESSION not in days
    assert date(2026, 11, 5) in days


def test_a_complete_valuation_is_snapshotted(session: Session) -> None:
    user_id, _ = _book(session, ("AAPL", "USD", True))

    assert snapshot_user_navs(session, snapshot_date=SESSION) == 1
    snap = session.exec(
        select(PortfolioSnapshot).where(
            PortfolioSnapshot.user_id == user_id, PortfolioSnapshot.date == SESSION
        )
    ).one()
    assert snap.nav > 0
