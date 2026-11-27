"""A7.12 (M10.7): India capital gains on listed equity, worked by hand."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from jose import jwt as jose_jwt
from sqlmodel import Session

from stockviz.models import PriceBar, User
from stockviz.models.portfolio import Portfolio, Trade, TradeSide
from stockviz.services.tax.lots import Fill, Realised, build_lots, compute_fy
from stockviz.services.tax.rules import FY_RULES, fy_of, is_long_term
from stockviz.settings import get_settings
from tests.symbols import seed_symbols

D = Decimal
FY26 = FY_RULES["2025-26"]
FY27 = FY_RULES["2026-27"]


def _fill(day: str, side: str, qty: int, price: str, seq: int = 0, t: str = "TCS.NS") -> Fill:
    return Fill(t, date.fromisoformat(day), side, D(qty), D(price), seq)


def test_fy_and_the_twelve_month_line() -> None:
    assert fy_of(date(2026, 3, 31)) == "2025-26" and fy_of(date(2026, 4, 1)) == "2026-27"
    assert not is_long_term(date(2025, 4, 10), date(2026, 4, 10))
    assert is_long_term(date(2025, 4, 10), date(2026, 4, 11))
    # 29 Feb: the anniversary is 28 Feb.
    assert is_long_term(date(2024, 2, 29), date(2025, 3, 1))
    assert not is_long_term(date(2024, 2, 29), date(2025, 2, 28))


def test_fifo_splits_one_sell_across_a_long_and_a_short_lot() -> None:
    book = build_lots(
        [
            _fill("2024-01-10", "buy", 100, "100", 0),
            _fill("2025-03-01", "buy", 50, "120", 1),
            _fill("2025-06-02", "sell", 120, "150", 2),
        ]
    )
    long, short = book.realised
    assert (long.term, long.quantity, long.gain) == ("long", D(100), D("5000.00"))
    assert (short.term, short.quantity, short.cost, short.gain) == (
        "short",
        D(20),
        D("2400.00"),
        D("600.00"),
    )
    (left,) = book.open_lots
    assert (left.quantity, left.price, left.bought) == (D(30), D(120), date(2025, 3, 1))


def test_same_day_offsets_are_intraday_not_capital_gains() -> None:
    book = build_lots(
        [
            _fill("2025-05-05", "buy", 10, "100", 0),
            _fill("2025-05-05", "sell", 10, "105", 1),
            _fill("2025-05-06", "buy", 5, "100", 2),
            _fill("2025-05-06", "sell", 8, "110", 3),
        ]
    )
    assert [(i.day.day, i.quantity, i.pnl) for i in book.intraday] == [
        (5, D(10), D("50.00")),
        (6, D(5), D("50.00")),
    ]
    assert book.realised == []
    assert book.unmatched == [("TCS.NS", date(2025, 5, 6), D(3))]


@pytest.mark.parametrize(
    ("sale", "cost", "grandfathered"),
    [("100", "800.00", True), ("70", "700.00", True), ("40", "500.00", False)],
)
def test_grandfathering_takes_the_higher_of_cost_and_the_lower_of_fmv_and_sale(
    sale: str, cost: str, grandfathered: bool
) -> None:
    book = build_lots(
        [_fill("2017-06-01", "buy", 10, "50"), _fill("2025-06-02", "sell", 10, sale, 1)],
        fmv_2018={"TCS.NS": D(80)},
    )
    (r,) = book.realised
    assert r.cost == D(cost) and r.grandfathered is grandfathered


def _r(term: str, gain: str, sold: str = "2026-06-01") -> Realised:
    g = D(gain)
    return Realised("X", date(2024, 1, 1), date.fromisoformat(sold), D(1), D(0), g, g, term)


def test_set_off_exemption_tax_and_cess_by_hand() -> None:
    out = compute_fy(
        [_r("short", "100000"), _r("short", "-30000"), _r("long", "200000"), _r("long", "-50000")],
        [],
        FY27,
    )
    # Short: 100,000 - 30,000 = 70,000 at 20% = 14,000.
    # Long: 200,000 - 50,000 = 150,000; less 1,25,000 = 25,000 at 12.5% = 3,125.
    # Cess 4% of 17,125 = 685; total 17,810.
    assert (out.net_short, out.net_long_before_exemption) == (D(70000), D(150000))
    assert (out.exemption_used, out.exemption_left, out.taxable_long) == (
        D(125000),
        D(0),
        D(25000),
    )
    assert (out.tax_short, out.tax_long, out.cess, out.total_tax) == (
        D("14000.00"),
        D("3125.00"),
        D("685.00"),
        D("17810.00"),
    )


def test_short_losses_reach_long_gains_but_long_losses_never_reach_short_gains() -> None:
    out = compute_fy([_r("short", "-40000"), _r("long", "150000")], [], FY27)
    assert out.net_short == 0 and out.net_long_before_exemption == D(110000)
    assert out.taxable_long == 0 and out.exemption_left == D(15000) and out.total_tax == 0
    out2 = compute_fy([_r("short", "50000"), _r("long", "-80000")], [], FY27)
    assert out2.taxable_short == D(50000) and out2.loss_carried_long == D(80000)
    assert out2.tax_short == D("10000.00")


def test_surcharge_is_capped_and_other_years_are_left_out() -> None:
    out = compute_fy(
        [_r("short", "100000"), _r("short", "99999", sold="2026-03-31")],
        [],
        FY27,
        surcharge_rate=D("0.37"),
    )
    assert out.stcg == D(100000)
    assert out.surcharge == D("3000.00")  # 15% cap on 20,000
    assert out.cess == D("920.00")


# --- the route ---------------------------------------------------------------

SECRET = get_settings().internal_api_token


def _auth(user_id: int) -> dict[str, str]:
    return {
        "Authorization": "Bearer "
        + jose_jwt.encode({"sub": str(user_id)}, SECRET, algorithm="HS256")
    }


def _book(session: Session, email: str, currency: str = "INR") -> tuple[int, int]:
    user = User(email=email, name=email)
    session.add(user)
    session.commit()
    session.refresh(user)
    assert user.id is not None
    book = Portfolio(user_id=user.id, cash_balance=D("1000000"), base_currency=currency)
    session.add(book)
    session.commit()
    session.refresh(book)
    assert book.id is not None
    return user.id, book.id


def _trade(
    session: Session, book: int, ticker: str, side: TradeSide, qty: int, price: str, ts: datetime
) -> None:
    session.add(
        Trade(portfolio_id=book, ticker=ticker, side=side, quantity=D(qty), price=D(price), ts=ts)
    )


def test_route_estimates_an_inr_book(client: TestClient, session: Session) -> None:
    seed_symbols(session, "TCS.NS", "AAPL", currency="INR")
    uid, book = _book(session, "tax@stockviz.dev")
    # 10:00 IST buys and sells: venue days in India.
    _trade(session, book, "TCS.NS", TradeSide.BUY, 100, "3000", datetime(2025, 1, 6, 4, 30))
    _trade(session, book, "TCS.NS", TradeSide.SELL, 60, "4000", datetime(2026, 5, 4, 4, 30))
    _trade(session, book, "TCS.NS", TradeSide.BUY, 20, "3500", datetime(2026, 6, 1, 4, 30))
    session.add(PriceBar(ticker="TCS.NS", interval="1d", ts=datetime(2026, 11, 20), open=D(3600),
                         high=D(3650), low=D(3550), close=D(3600), volume=1))  # fmt: skip
    session.commit()
    out = client.get(f"/v1/tax/india?book={book}&fy=2026-27", headers=_auth(uid)).json()
    c = out["computation"]
    # 60 long-term shares: 60,000 gain, inside the 1,25,000 exemption.
    assert D(c["ltcg"]) == D(60000) and D(c["exemption_left"]) == D(65000)
    assert D(c["total_tax"]) == 0
    assert out["rules"]["ltcg_section"] == "198" and out["rules"]["sources"]
    lots = {(lot["bought"], lot["term"]) for lot in out["open_lots"]}
    assert lots == {("2025-01-06", "long"), ("2026-06-01", "short")}
    assert "estimate" in out["estimate_note"].lower()
    assert out["method"]

    other_uid, _ = _book(session, "other@stockviz.dev")
    assert client.get(f"/v1/tax/india?book={book}", headers=_auth(other_uid)).status_code == 404
    assert (
        client.get(f"/v1/tax/india?book={book}&fy=2019-20", headers=_auth(uid)).status_code == 400
    )
    assert client.get("/v1/tax/india").status_code == 401


def test_route_refuses_a_usd_book(client: TestClient, session: Session) -> None:
    uid, book = _book(session, "usd@stockviz.dev", currency="USD")
    response = client.get(f"/v1/tax/india?book={book}&fy=2026-27", headers=_auth(uid))
    assert response.status_code == 409 and "INR books only" in response.json()["detail"]
