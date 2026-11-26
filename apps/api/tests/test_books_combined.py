"""A5.2 All books: two books in different currencies summed in the display currency.

The design note's rule ("Analytics per book and combined"): each book's NAV
converted at that date's rate, summed; TWR chained over the sum with a new
book's opening value and an imported book's buys and sells as outside flows;
a stale or missing rate is a warning, never a silent zero.

Hand calculation used by the first and last tests (display USD, USD per INR
0.012, 0.012, 0.0125 on d0, d1, d2):

    book A (USD, opened d0 at 100,000):  100,000   101,000   102,000
    book B (INR, opened d1 at ₹1 crore):        -  10,000,000 10,100,000
    B in USD:                                   -   120,000   126,250
    sum:                                  100,000   221,000   228,250
    flow (B's opening, d1):                         120,000
    d1 return: (221,000 - 120,000) / 100,000 - 1 = 1.0000%
    d2 return: 228,250 / 221,000 - 1            = 3.2805%
    TWR: 1.01 x 1.0328054299 - 1                = 4.3133%
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from jose import jwt as jose_jwt
from sqlmodel import Session, select

from stockviz._time import utcnow
from stockviz.models import BookKind, FxRate, Portfolio, PortfolioSnapshot, Trade, TradeSide, User
from stockviz.services.books.combined import (
    BookSeries,
    RateBook,
    combine,
    growth_index,
    imported_flows,
)
from stockviz.services.trading.books import ensure_default_portfolio
from stockviz.services.trading.returns import time_weighted_return
from stockviz.settings import get_settings

D = Decimal
SECRET = get_settings().internal_api_token

# Monday to Wednesday: each date has its own rate, so none is stale.
D0, D1, D2 = date(2026, 11, 2), date(2026, 11, 3), date(2026, 11, 4)
TWR_PCT = (1.01 * (228250 / 221000) - 1) * 100  # 4.31334...


def _rates(**by_ccy: list[tuple[date, str]]) -> RateBook:
    book = RateBook()
    for ccy, rows in by_ccy.items():
        book.by_currency[ccy] = ([d for d, _ in rows], [D(r) for _, r in rows])
    return book


def _convert(rates: RateBook, display: str = "USD"):
    def convert(amount, ccy, day, notes):
        return rates.convert(amount, src=ccy, dst=display, day=day, notes=notes)

    return convert


BOOK_A = BookSeries(
    1, "USD", D0, [(D0, D(100000)), (D1, D(101000)), (D2, D(102000))], opening=D(100000)
)
BOOK_B = BookSeries(2, "INR", D1, [(D1, D(10_000_000)), (D2, D(10_100_000))], opening=D(10_000_000))
INR = [(D0, "0.012"), (D1, "0.012"), (D2, "0.0125")]


def test_two_books_in_usd_and_inr_sum_at_each_dates_rate() -> None:
    out = combine([BOOK_A, BOOK_B], display="USD", convert=_convert(_rates(INR=INR)))

    assert out.opened == D0
    assert out.points == [(D0, D(100000)), (D1, D(221000)), (D2, D(228250))]
    assert out.flows == [(D1, D(120000))]
    assert out.notes == []
    twr = time_weighted_return(out.points, out.flows)
    assert twr is not None
    assert twr * 100 == pytest.approx(TWR_PCT, abs=1e-9)
    assert round(TWR_PCT, 4) == 4.3133
    # The flow-free index ends where the TWR says: 100,000 x 1.043133...
    assert float(growth_index(out.points, out.flows)[-1][1]) == pytest.approx(104313.3484, abs=1e-3)


def test_the_same_books_in_rupees() -> None:
    """Display INR: A's dollars at 1 / 0.012 = 83.33..., then 80 on d2."""
    out = combine([BOOK_A, BOOK_B], display="INR", convert=_convert(_rates(INR=INR), "INR"))
    # d2: 102,000 / 0.0125 = 8,160,000 + 10,100,000.
    assert out.points[-1] == (D2, D(18_260_000))
    assert out.flows == [(D1, D(10_000_000))]


def test_an_imported_books_buys_and_sells_are_flows() -> None:
    """A USD paper book flat at 100,000 and a holdings-only book.

    d1: buy 50 at 100 (flow +5,000; value 5,000). d2: close 110, sell 20
    (flow -2,200; value 30 x 110 = 3,300). The only gain is 10 a share on 50:
    d1 return 0; d2 (103,300 + 2,200) / 105,000 - 1 = 0.47619%.
    """
    flat = BookSeries(1, "USD", D0, [(D0, D(100000)), (D1, D(100000)), (D2, D(100000))])
    imported = BookSeries(
        3,
        "USD",
        D0,
        [(D0, D(0)), (D1, D(5000)), (D2, D(3300))],
        flows=[(D1, D(5000)), (D2, D(-2200))],
    )
    out = combine([flat, imported], display="USD", convert=_convert(_rates()))
    assert out.points == [(D0, D(100000)), (D1, D(105000)), (D2, D(103300))]
    assert out.flows == [(D1, D(5000)), (D2, D(-2200))]
    twr = time_weighted_return(out.points, out.flows)
    assert twr is not None
    assert twr * 100 == pytest.approx((105500 / 105000 - 1) * 100, abs=1e-12)
    assert round(twr * 100, 5) == 0.47619


def test_imported_flows_read_from_trades(session: Session) -> None:
    user = User(email=f"{uuid4().hex}@stockviz.dev", name="Imp")
    session.add(user)
    session.commit()
    assert user.id is not None
    book = Portfolio(
        user_id=user.id,
        name="Zerodha",
        kind=BookKind.IMPORTED,
        is_default=False,
        cash_tracked=False,
        cash_balance=D(0),
        opening_nav=D(0),
    )
    session.add(book)
    session.commit()
    assert book.id is not None
    from stockviz.models import Symbol

    session.add(Symbol(ticker="IMPX", name="IMPX", currency="USD"))
    session.commit()
    for side, qty, price, fees, day in (
        (TradeSide.BUY, "50", "100", "1", D1),
        (TradeSide.SELL, "20", "110", "2", D2),
    ):
        session.add(
            Trade(
                portfolio_id=book.id,
                ticker="IMPX",
                side=side,
                quantity=D(qty),
                price=D(price),
                fees=D(fees),
                fx_rate=D(1),
                ts=datetime.combine(day, datetime.min.time()) + timedelta(hours=15),
            )
        )
    session.commit()
    # Buy: 5,000 + 1 fee in; sell: 2,200 - 2 fee out.
    assert imported_flows(session, book) == [(D1, D(5001)), (D2, D(-2198))]


def test_a_stale_rate_is_used_and_warned_a_missing_one_drops_the_date() -> None:
    # Only a rate from the Monday before: Wednesday's floor is Tuesday.
    stale = combine(
        [BOOK_A, BOOK_B],
        display="USD",
        convert=_convert(_rates(INR=[(date(2026, 10, 26), "0.012")])),
    )
    assert [p[0] for p in stale.points] == [D0, D1, D2]
    assert {(n.currency, n.day, n.rate_date) for n in stale.notes} == {
        ("INR", D1, date(2026, 10, 26)),
        ("INR", D2, date(2026, 10, 26)),
    }

    # No INR rate before d2: d1 is left out and B's opening counts on d2.
    missing = combine(
        [BOOK_A, BOOK_B], display="USD", convert=_convert(_rates(INR=[(D2, "0.0125")]))
    )
    assert missing.points == [(D0, D(100000)), (D2, D(228250))]
    assert missing.flows == [(D2, D(125000))]
    assert any(n.rate_date is None and n.day == D1 for n in missing.notes)


# --- The routes -----------------------------------------------------------------


def _h(user_id: int) -> dict[str, str]:
    token = jose_jwt.encode({"sub": str(user_id)}, SECRET, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


def _two_books(session: Session, *, inr_rates: list[tuple[date, str]]) -> tuple[int, int, int]:
    """The docstring's example dated today-2, today-1, today; cash only, so live = d2."""
    today = utcnow().date()
    d0, d1 = today - timedelta(days=2), today - timedelta(days=1)
    user = User(email=f"{uuid4().hex}@stockviz.dev", name="Two books")
    session.add(user)
    session.commit()
    assert user.id is not None
    a = ensure_default_portfolio(session, user.id)
    # Its day-zero snapshot is dated today; this book opened on d0 instead.
    for snap in session.exec(
        select(PortfolioSnapshot).where(PortfolioSnapshot.portfolio_id == a.id)
    ).all():
        session.delete(snap)
    a.created_at = datetime.combine(d0, datetime.min.time())
    a.opening_nav = D(100000)
    a.cash_balance = D(102000)
    b = Portfolio(
        user_id=user.id,
        name="India",
        is_default=False,
        base_currency="INR",
        cash_balance=D(10_100_000),
        opening_nav=D(10_000_000),
        created_at=datetime.combine(d1, datetime.min.time()),
    )
    session.add_all([a, b])
    session.commit()
    assert a.id is not None and b.id is not None
    session.add_all(
        [
            PortfolioSnapshot(user_id=user.id, portfolio_id=a.id, date=d0, nav=D(100000)),
            PortfolioSnapshot(user_id=user.id, portfolio_id=a.id, date=d1, nav=D(101000)),
            PortfolioSnapshot(user_id=user.id, portfolio_id=b.id, date=d1, nav=D(10_000_000)),
        ]
    )
    for day, rate in inr_rates:
        session.add(FxRate(currency="INR", date=day, usd_rate=D(rate)))
    session.commit()
    return user.id, a.id, b.id


def test_all_books_on_the_routes(session: Session, client: TestClient) -> None:
    today = utcnow().date()
    user_id, a_id, b_id = _two_books(
        session,
        inr_rates=[
            (today - timedelta(days=2), "0.012"),
            (today - timedelta(days=1), "0.012"),
            (today, "0.0125"),
        ],
    )

    overview = client.get("/v1/portfolio/overview?book=all", headers=_h(user_id))
    assert overview.status_code == 200, overview.text
    body = overview.json()
    portfolio = body["portfolio"]
    assert portfolio["portfolio_id"] == 0
    assert D(portfolio["total_value"]) == D(228250)
    assert portfolio["valuation_warnings"] == []
    assert [b["id"] for b in portfolio["combined"]["books"]] == [a_id, b_id]
    assert "stress tests" in portfolio["combined"]["per_book_only"]
    returns = body["analytics"]["returns"]
    assert returns["currency"] == "USD"
    all_period = next(p for p in returns["periods"] if p["period"] == "ALL")
    assert all_period["return_pct"] == pytest.approx(TWR_PCT, abs=1e-9)
    assert body["analytics"]["total_return_pct"] == pytest.approx(TWR_PCT, abs=1e-6)
    assert body["analytics"]["attribution"] is None

    history = client.get("/v1/portfolio/history?book=all", headers=_h(user_id)).json()
    assert [(D(h["nav"]), D(h["flow"])) for h in history] == [
        (D(100000), D(0)),
        (D(221000), D(120000)),
    ]
    # One book's own history is unchanged and carries no flow.
    own = client.get(f"/v1/portfolio/history?book={b_id}", headers=_h(user_id)).json()
    assert [h["flow"] for h in own] == [None]

    # Risk and stress stay per book.
    assert client.get("/v1/portfolio/risk?book=all", headers=_h(user_id)).status_code == 422
    assert client.get("/v1/portfolio/stress?book=all", headers=_h(user_id)).status_code == 422
    assert client.get("/v1/portfolio?book=allx", headers=_h(user_id)).status_code == 422


def test_all_books_trades_and_orders_name_their_book(session: Session, client: TestClient) -> None:
    today = utcnow().date()
    user_id, a_id, b_id = _two_books(session, inr_rates=[(today, "0.0125")])
    from stockviz.models import PendingOrder, Symbol
    from stockviz.models.order import OrderStatus, OrderType

    session.add(Symbol(ticker="CMBX", name="CMBX", currency="USD"))
    session.commit()
    ts = datetime.combine(today, datetime.min.time())
    session.add_all(
        [
            Trade(portfolio_id=a_id, ticker="CMBX", side=TradeSide.BUY, quantity=D(1),
                  price=D(10), fx_rate=D(1), ts=ts),
            Trade(portfolio_id=b_id, ticker="CMBX", side=TradeSide.BUY, quantity=D(2),
                  price=D(10), fx_rate=D(80), ts=ts + timedelta(minutes=1)),
            PendingOrder(portfolio_id=b_id, ticker="CMBX", side=TradeSide.BUY,
                         order_type=OrderType.LIMIT, quantity=D(1), limit_price=D(9),
                         status=OrderStatus.PENDING),
        ]
    )  # fmt: skip
    session.commit()

    trades = client.get("/v1/trades?book=all", headers=_h(user_id)).json()
    assert [(t["book_id"], t["base_currency"]) for t in trades] == [(b_id, "INR"), (a_id, "USD")]
    assert D(trades[0]["total_base"]) == D(1600)
    one = client.get(f"/v1/trades?book={a_id}", headers=_h(user_id)).json()
    assert [t["book_id"] for t in one] == [a_id]

    orders = client.get("/v1/orders?book=all&status=pending", headers=_h(user_id)).json()
    assert [o["portfolio_id"] for o in orders] == [b_id]
    assert client.get(f"/v1/orders?book={a_id}", headers=_h(user_id)).json() == []


def test_all_books_warns_on_a_stale_rate(session: Session, client: TestClient) -> None:
    today = utcnow().date()
    user_id, _, _ = _two_books(session, inr_rates=[(today - timedelta(days=12), "0.012")])
    portfolio = client.get("/v1/portfolio?book=all", headers=_h(user_id)).json()
    codes = {(w["code"], w["subject"]) for w in portfolio["valuation_warnings"]}
    assert ("stale_fx_rate", "INR") in codes
    # The stale rate is still used, never a zero: 102,000 + 10,100,000 x 0.012.
    assert D(portfolio["total_value"]) == D(223200)


def test_another_users_book_is_still_404(session: Session, client: TestClient) -> None:
    today = utcnow().date()
    _, _, b_id = _two_books(session, inr_rates=[(today, "0.0125")])
    other, _, _ = _two_books(session, inr_rates=[])
    assert client.get(f"/v1/portfolio?book={b_id}", headers=_h(other)).status_code == 404
    assert client.get(f"/v1/trades?book={b_id}", headers=_h(other)).status_code == 404
