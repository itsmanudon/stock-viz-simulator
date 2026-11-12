"""Tests for dividend ingest, credit service, and GET /v1/portfolio/dividends."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from fastapi.testclient import TestClient
from jose import jwt as jose_jwt
from sqlmodel import Session, select

from stockviz.models import Portfolio, Position, Symbol, User
from stockviz.models.dividend import Dividend, PortfolioDividend
from stockviz.services.ingest.dividends import ingest_dividends_for_ticker
from stockviz.services.trading.dividends import credit_due_dividends
from stockviz.settings import get_settings

SECRET = get_settings().internal_api_token


def _auth_headers(user_id: int) -> dict[str, str]:
    token = jose_jwt.encode({"sub": str(user_id)}, SECRET, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


def _seed_symbol(session: Session, ticker: str = "AAPL") -> None:
    session.add(Symbol(ticker=ticker, name=f"{ticker} Inc.", sector="Technology"))
    session.commit()


def _make_portfolio(session: Session, email: str = "div@stockviz.dev") -> tuple[int, int]:
    """Returns (user_id, portfolio_id)."""
    user = User(email=email, name="Div Trader")
    session.add(user)
    session.commit()
    session.refresh(user)
    portfolio = Portfolio(
        user_id=user.id,  # type: ignore[arg-type]
        cash_balance=Decimal("100000"),
        # Opened before the ex-dates these tests use: a book is not owed
        # dividends from before it existed (LG-12).
        created_at=datetime(2026, 1, 2),
    )
    session.add(portfolio)
    session.commit()
    session.refresh(portfolio)
    return user.id, portfolio.id  # type: ignore[return-value]


def _add_position(
    session: Session,
    portfolio_id: int,
    ticker: str,
    quantity: Decimal,
    avg_cost: Decimal = Decimal("150"),
) -> None:
    session.add(
        Position(portfolio_id=portfolio_id, ticker=ticker, quantity=quantity, avg_cost=avg_cost)
    )
    session.commit()


def _add_dividend(session: Session, ticker: str, ex_date: date, amount: Decimal) -> None:
    session.add(Dividend(ticker=ticker, ex_date=ex_date, amount=amount))
    session.commit()


# ---------------------------------------------------------------------------
# Ingest service
# ---------------------------------------------------------------------------


def test_ingest_stores_dividends(session: Session) -> None:
    _seed_symbol(session, "AAPL")

    def fake_fetch(ticker: str):
        return [(date(2026, 3, 7), Decimal("0.25")), (date(2026, 6, 6), Decimal("0.25"))]

    written = ingest_dividends_for_ticker(session, "AAPL", fetch_fn=fake_fetch)
    assert written == 2
    rows = list(session.exec(select(Dividend).where(Dividend.ticker == "AAPL")))
    assert len(rows) == 2


def test_ingest_is_idempotent(session: Session) -> None:
    _seed_symbol(session, "AAPL")

    def fake_fetch(ticker: str):
        return [(date(2026, 3, 7), Decimal("0.25"))]

    ingest_dividends_for_ticker(session, "AAPL", fetch_fn=fake_fetch)
    written2 = ingest_dividends_for_ticker(session, "AAPL", fetch_fn=fake_fetch)
    assert written2 == 0  # same amount, not rewritten


def test_ingest_updates_corrected_amount(session: Session) -> None:
    _seed_symbol(session, "AAPL")

    def v1(ticker):
        return [(date(2026, 3, 7), Decimal("0.25"))]

    def v2(ticker):
        return [(date(2026, 3, 7), Decimal("0.26"))]  # corrected

    ingest_dividends_for_ticker(session, "AAPL", fetch_fn=v1)
    written = ingest_dividends_for_ticker(session, "AAPL", fetch_fn=v2)
    assert written == 1
    row = session.exec(select(Dividend).where(Dividend.ticker == "AAPL")).first()
    assert row is not None
    assert row.amount == Decimal("0.26")


def test_ingest_skips_unknown_ticker(session: Session) -> None:
    def fake_fetch(ticker: str):
        return [(date(2026, 3, 7), Decimal("0.25"))]

    written = ingest_dividends_for_ticker(session, "UNKN", fetch_fn=fake_fetch)
    assert written == 0


# ---------------------------------------------------------------------------
# Credit service
# ---------------------------------------------------------------------------


def test_credit_due_adds_cash_and_audit_row(session: Session) -> None:
    _seed_symbol(session, "AAPL")
    _user_id, portfolio_id = _make_portfolio(session)
    _add_position(session, portfolio_id, "AAPL", Decimal("10"))
    _add_dividend(session, "AAPL", date(2026, 3, 7), Decimal("0.25"))

    credited = credit_due_dividends(session, credit_date=date(2026, 3, 7))
    assert credited == 1

    portfolio = session.get(Portfolio, portfolio_id)
    assert portfolio is not None
    assert portfolio.cash_balance == Decimal("100002.5")  # 100000 + 10*0.25

    audit = session.exec(
        select(PortfolioDividend).where(PortfolioDividend.portfolio_id == portfolio_id)
    ).first()
    assert audit is not None
    assert audit.amount_credited == Decimal("2.5")
    assert audit.ticker == "AAPL"


def test_credit_is_idempotent(session: Session) -> None:
    _seed_symbol(session, "AAPL")
    _user_id, portfolio_id = _make_portfolio(session)
    _add_position(session, portfolio_id, "AAPL", Decimal("10"))
    _add_dividend(session, "AAPL", date(2026, 3, 7), Decimal("0.25"))

    credit_due_dividends(session, credit_date=date(2026, 3, 7))
    credit_due_dividends(session, credit_date=date(2026, 3, 7))  # second run

    portfolio = session.get(Portfolio, portfolio_id)
    assert portfolio is not None
    assert portfolio.cash_balance == Decimal("100002.5")  # credited exactly once


def test_credit_skips_a_holding_already_sold(session: Session) -> None:
    # A position sold to zero is deleted (positions.quantity > 0, audit LG-11).
    _seed_symbol(session, "AAPL")
    _make_portfolio(session)
    _add_dividend(session, "AAPL", date(2026, 3, 7), Decimal("0.25"))

    credited = credit_due_dividends(session, credit_date=date(2026, 3, 7))
    assert credited == 0


def test_credit_no_dividends_on_date_is_noop(session: Session) -> None:
    _seed_symbol(session, "AAPL")
    _user_id, portfolio_id = _make_portfolio(session)
    _add_position(session, portfolio_id, "AAPL", Decimal("10"))

    credited = credit_due_dividends(session, credit_date=date(2026, 3, 7))
    assert credited == 0


# ---------------------------------------------------------------------------
# GET /v1/portfolio/dividends
# ---------------------------------------------------------------------------


def test_dividends_endpoint_requires_auth(client: TestClient) -> None:
    assert client.get("/v1/portfolio/dividends").status_code == 401


def test_dividends_endpoint_empty(session: Session, client: TestClient) -> None:
    user = User(email="empty@stockviz.dev", name="Empty")
    session.add(user)
    session.commit()
    session.refresh(user)

    resp = client.get("/v1/portfolio/dividends", headers=_auth_headers(user.id))  # type: ignore[arg-type]
    assert resp.status_code == 200
    body = resp.json()
    assert Decimal(body["ytd_income"]) == Decimal("0")
    assert body["history"] == []
    assert body["projected"] == []


def test_dividends_endpoint_shows_credits_and_projected(
    session: Session, client: TestClient
) -> None:
    _seed_symbol(session, "AAPL")
    user_id, portfolio_id = _make_portfolio(session, email="full@stockviz.dev")
    _add_position(session, portfolio_id, "AAPL", Decimal("10"))

    # Two historical dividends (for frequency estimation).
    _add_dividend(session, "AAPL", date(2025, 12, 6), Decimal("0.25"))
    _add_dividend(session, "AAPL", date(2026, 3, 7), Decimal("0.25"))

    # Credit the March one.
    session.add(
        PortfolioDividend(
            portfolio_id=portfolio_id,
            ticker="AAPL",
            ex_date=date(2026, 3, 7),
            amount_credited=Decimal("2.5"),
            credited_at=datetime(2026, 3, 7, 9, 30),
        )
    )
    session.commit()

    resp = client.get("/v1/portfolio/dividends", headers=_auth_headers(user_id))
    assert resp.status_code == 200
    body = resp.json()

    assert Decimal(body["ytd_income"]) == Decimal("2.5")
    assert len(body["history"]) == 1
    assert body["history"][0]["ticker"] == "AAPL"

    # Projected next payout should exist (gap ≈ 91 days → June 6 ish).
    assert len(body["projected"]) == 1
    proj = body["projected"][0]
    assert proj["ticker"] == "AAPL"
    assert proj["projected_ex_date"] is not None
    assert Decimal(proj["projected_amount"]) == Decimal("2.5")  # 10 shares * 0.25


# ---------------------------------------------------------------------------
# Catch-up and entitlement (audit LG-12, issue #66)
# ---------------------------------------------------------------------------


def _trade(session: Session, portfolio_id: int, side: str, qty: str, ts: datetime) -> None:
    from stockviz.models import Trade
    from stockviz.models.portfolio import TradeSide

    session.add(
        Trade(
            portfolio_id=portfolio_id,
            ticker="AAPL",
            side=TradeSide(side),
            quantity=Decimal(qty),
            price=Decimal("100"),
            ts=ts,
        )
    )
    session.commit()


def _cash(session: Session, portfolio_id: int) -> Decimal:
    portfolio = session.get(Portfolio, portfolio_id)
    assert portfolio is not None
    session.refresh(portfolio)
    return portfolio.cash_balance


def test_a_missed_ex_date_is_paid_by_the_next_run_once(session: Session) -> None:
    """#66: yesterday's ex-date, no run yesterday: today's run pays it, once."""
    _seed_symbol(session, "AAPL")
    _user_id, portfolio_id = _make_portfolio(session)
    _add_position(session, portfolio_id, "AAPL", Decimal("10"))
    _add_dividend(session, "AAPL", date(2026, 3, 6), Decimal("0.25"))
    _add_dividend(session, "AAPL", date(2026, 3, 9), Decimal("0.30"))

    assert credit_due_dividends(session, credit_date=date(2026, 3, 10)) == 2
    assert _cash(session, portfolio_id) == Decimal("100005.5")  # 10*0.25 + 10*0.30
    assert credit_due_dividends(session, credit_date=date(2026, 3, 10)) == 0


def test_a_future_ex_date_waits(session: Session) -> None:
    _seed_symbol(session, "AAPL")
    _user_id, portfolio_id = _make_portfolio(session)
    _add_position(session, portfolio_id, "AAPL", Decimal("10"))
    _add_dividend(session, "AAPL", date(2026, 3, 12), Decimal("0.25"))
    assert credit_due_dividends(session, credit_date=date(2026, 3, 10)) == 0


def test_missing_fx_is_paid_by_a_later_run_once_a_rate_exists(session: Session) -> None:
    from stockviz.models import FxRate

    session.add(Symbol(ticker="AAPL", name="Apple", currency="GBP"))
    session.commit()
    _user_id, portfolio_id = _make_portfolio(session)
    _add_position(session, portfolio_id, "AAPL", Decimal("10"))
    _add_dividend(session, "AAPL", date(2026, 3, 6), Decimal("1"))

    assert credit_due_dividends(session, credit_date=date(2026, 3, 6)) == 0
    session.add(FxRate(currency="GBP", date=date(2026, 3, 5), usd_rate=Decimal("1.25")))
    session.commit()
    assert credit_due_dividends(session, credit_date=date(2026, 3, 9)) == 1
    assert _cash(session, portfolio_id) == Decimal("100012.5")  # 10 GBP at 1.25


def test_a_buyer_on_the_ex_date_is_not_paid(session: Session) -> None:
    """LG-12: holdings at job time paid a same-day buyer."""
    _seed_symbol(session, "AAPL")
    _user_id, portfolio_id = _make_portfolio(session)
    _add_position(session, portfolio_id, "AAPL", Decimal("10"))
    _trade(session, portfolio_id, "buy", "10", datetime(2026, 3, 6, 15, 0))  # 10:00 New York
    _add_dividend(session, "AAPL", date(2026, 3, 6), Decimal("0.25"))

    assert credit_due_dividends(session, credit_date=date(2026, 3, 6)) == 0


def test_a_holder_who_sold_on_the_ex_date_is_paid(session: Session) -> None:
    """LG-12: holdings at job time skipped a holder who sold on the ex-date."""
    _seed_symbol(session, "AAPL")
    _user_id, portfolio_id = _make_portfolio(session)
    _trade(session, portfolio_id, "buy", "10", datetime(2026, 3, 2, 15, 0))
    _trade(session, portfolio_id, "sell", "10", datetime(2026, 3, 6, 15, 0))
    # Sold to zero: the position row is gone, the trades remain.
    _add_dividend(session, "AAPL", date(2026, 3, 6), Decimal("0.25"))

    assert credit_due_dividends(session, credit_date=date(2026, 3, 6)) == 1
    assert _cash(session, portfolio_id) == Decimal("100002.5")


def test_the_new_york_date_decides_the_side_of_the_ex_date(session: Session) -> None:
    """01:00 UTC on the ex-date is 20:00 New York the evening before: entitled."""
    _seed_symbol(session, "AAPL")
    _user_id, portfolio_id = _make_portfolio(session)
    _add_position(session, portfolio_id, "AAPL", Decimal("10"))
    _trade(session, portfolio_id, "buy", "10", datetime(2026, 3, 6, 1, 0))
    _add_dividend(session, "AAPL", date(2026, 3, 6), Decimal("0.25"))

    assert credit_due_dividends(session, credit_date=date(2026, 3, 6)) == 1


def test_a_portfolio_is_not_owed_dividends_from_before_it_opened(session: Session) -> None:
    _seed_symbol(session, "AAPL")
    _user_id, portfolio_id = _make_portfolio(session)  # opened 2 Jan 2026
    _add_position(session, portfolio_id, "AAPL", Decimal("10"))
    _add_dividend(session, "AAPL", date(2025, 11, 7), Decimal("0.25"))

    assert credit_due_dividends(session, credit_date=date(2026, 3, 6)) == 0
