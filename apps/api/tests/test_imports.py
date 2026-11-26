"""A5.3: the Zerodha tradebook CSV import into an imported book.

Every fixture is synthetic: invented trade ids, prices and dates. No real
tradebook enters the repository.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from jose import jwt as jose_jwt
from sqlmodel import Session, col, select

from stockviz.models import (
    BrokerFill,
    CorporateAction,
    ImportBatch,
    InstrumentIdentifier,
    Portfolio,
    Position,
    PriceBar,
    Symbol,
    Trade,
    User,
)
from stockviz.models.trade_plan import TradePlan
from stockviz.observability import scrub_event
from stockviz.services.books.combined import imported_flows
from stockviz.services.corporate_actions.apply import apply_due_splits
from stockviz.services.imports.columns import match_headers, normalise_header
from stockviz.services.imports.parse import (
    MAX_FILE_BYTES,
    infer_date_order,
    parse_date,
    parse_tradebook,
)
from stockviz.services.instruments import resolve_symbol
from stockviz.services.simulation import OrderSide, get_fee_schedule
from stockviz.settings import get_settings

SECRET = get_settings().internal_api_token
HEADER = (
    "symbol,isin,trade_date,exchange,segment,series,trade_type,auction,quantity,price,"
    "trade_id,order_id,order_execution_time"
)
RELIANCE_ISIN = "INE000A01011"  # invented
TODAY = date(2026, 11, 26)


def _h(user_id: int) -> dict[str, str]:
    token = jose_jwt.encode({"sub": str(user_id)}, SECRET, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


def _user(session: Session) -> int:
    user = User(email=f"{uuid4().hex}@stockviz.dev", name="Importer")
    session.add(user)
    session.commit()
    session.refresh(user)
    assert user.id is not None
    return user.id


def _symbols(session: Session) -> None:
    for ticker in ("RELIANCE.NS", "TCS.NS", "INFY.BO"):
        if session.get(Symbol, ticker) is None:
            session.add(Symbol(ticker=ticker, name=ticker, currency="INR"))
    session.commit()
    inst = resolve_symbol(session, "RELIANCE.NS")
    assert inst is not None and inst.id is not None
    session.add(
        InstrumentIdentifier(
            instrument_id=inst.id, scheme="isin", value=RELIANCE_ISIN, valid_from=date(2020, 1, 1)
        )
    )
    session.commit()


def _book(client: TestClient, uid: int, **body) -> int:
    body.setdefault("name", f"Zerodha {uuid4().hex[:5]}")
    body.setdefault("kind", "imported")
    body.setdefault("base_currency", "INR")
    r = client.post("/v1/books", json=body, headers=_h(uid))
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _row(
    symbol: str,
    day: str,
    side: str,
    qty: str,
    price: str,
    trade_id: str,
    *,
    time: str = "10:15:00",
    exchange: str = "NSE",
    segment: str = "EQ",
    isin: str = "",
    order_id: str = "",
) -> str:
    executed = f"{day}T{time}" if time else ""
    return (
        f"{symbol},{isin},{day},{exchange},{segment},EQ,{side},false,{qty},{price},"
        f"{trade_id},{order_id or 'ORD' + trade_id},{executed}"
    )


def _csv(*rows: str, header: str = HEADER) -> bytes:
    return ("\n".join([header, *rows]) + "\n").encode()


def _preview(client: TestClient, uid: int, book: int, body: bytes):
    return client.post(
        f"/v1/books/{book}/imports/preview",
        content=body,
        headers={**_h(uid), "Content-Type": "text/csv"},
    )


def _commit(client: TestClient, uid: int, book: int, body: bytes, sha: str | None = None):
    if sha is None:
        sha = _preview(client, uid, book, body).json()["file_sha256"]
    return client.post(
        f"/v1/books/{book}/imports/commit?file_sha256={sha}",
        content=body,
        headers={**_h(uid), "Content-Type": "text/csv"},
    )


def _positions(session: Session, book: int) -> dict[str, tuple[Decimal, Decimal]]:
    session.expire_all()
    return {
        p.ticker: (p.quantity, p.avg_cost)
        for p in session.exec(select(Position).where(Position.portfolio_id == book)).all()
    }


def _trades(session: Session, book: int) -> list[Trade]:
    session.expire_all()
    return list(
        session.exec(
            select(Trade).where(Trade.portfolio_id == book).order_by(col(Trade.ts), col(Trade.id))
        ).all()
    )


# --- parsing ---------------------------------------------------------------------


def test_header_aliases_match_ignoring_case_spaces_and_underscores() -> None:
    assert normalise_header("﻿Trade Date") == "tradedate"
    match = match_headers(
        [
            "Trading Symbol",
            "ISIN",
            "Trade Date",
            "Exchange",
            "Buy/Sell",
            "Qty",
            "Trade Price",
            "Trade No",
            "Order Execution Time",
            "Client ID",
        ]
    )
    by = {c.field: c.header for c in match.columns}
    assert by["symbol"] == "Trading Symbol"
    assert by["side"] == "Buy/Sell"
    assert by["quantity"] == "Qty"
    assert by["price"] == "Trade Price"
    assert by["trade_id"] == "Trade No"
    assert by["executed_at"] == "Order Execution Time"
    assert match.unmatched_headers == ("Client ID",)
    assert match.missing_required == ()
    assert match_headers(["symbol", "trade_date"]).missing_required == (
        "exchange",
        "side",
        "quantity",
        "price",
        "trade_id",
    )


def test_date_formats_and_the_files_own_day_month_order() -> None:
    assert parse_date("2025-04-03", "none") == date(2025, 4, 3)
    assert parse_date("03-Apr-2025", "none") == date(2025, 4, 3)
    assert parse_date("3 April 2025", "none") == date(2025, 4, 3)
    assert parse_date("Apr 3, 2025", "none") == date(2025, 4, 3)
    assert parse_date("13/04/2025", "ambiguous") == date(2025, 4, 13)
    assert parse_date("05/05/25", "ambiguous") == date(2025, 5, 5)
    assert infer_date_order(["13/04/2025", "03/04/2025"]) == "day_first"
    assert infer_date_order(["04/13/2025", "03/04/2025"]) == "month_first"
    assert infer_date_order(["13/04/2025", "04/13/2025"]) == "conflicting"
    assert infer_date_order(["03/04/2025"]) == "ambiguous"
    assert parse_date("03/04/2025", "day_first") == date(2025, 4, 3)
    assert parse_date("03/04/2025", "month_first") == date(2025, 3, 4)
    with pytest.raises(ValueError, match="ambiguous"):
        parse_date("03/04/2025", "ambiguous")
    with pytest.raises(ValueError, match="ambiguous"):
        parse_date("03/04/2025", "conflicting")
    with pytest.raises(ValueError, match="real calendar date"):
        parse_date("2025-02-30", "none")


def test_ambiguous_rows_are_rejected_not_guessed_and_times_are_ist() -> None:
    body = _csv(
        "RELIANCE,,03/04/2025,NSE,EQ,EQ,buy,false,1,100,T1,O1,09:15:30",
        "RELIANCE,,05/05/2025,NSE,EQ,EQ,sell,false,1,110,T2,O2,03:20 PM",
    )
    parsed = parse_tradebook(body, today=TODAY)
    assert parsed.date_order == "ambiguous"
    assert [(p.row, p.field) for p in parsed.problems] == [(2, "trade_date")]
    assert "ambiguous" in parsed.problems[0].reason
    (row,) = parsed.rows
    # 15:20 IST is 09:50 UTC.
    assert row.row == 3 and row.executed_at == datetime(2025, 5, 5, 9, 50) and row.time_known
    day_first = parse_tradebook(
        _csv(
            "RELIANCE,,03/04/2025,NSE,EQ,EQ,buy,false,1,100,T1,O1,",
            "RELIANCE,,13/04/2025,NSE,EQ,EQ,sell,false,1,110,T2,O2,",
        ),
        today=TODAY,
    )
    assert [r.trade_date for r in day_first.rows] == [date(2025, 4, 3), date(2025, 4, 13)]
    # No time: the start of the IST trade date, marked unknown.
    assert day_first.rows[0].executed_at == datetime(2025, 4, 2, 18, 30)
    assert not day_first.rows[0].time_known


def test_bad_values_are_rejected_by_row_and_field_without_their_values() -> None:
    body = _csv(
        _row("RELIANCE", "2025-04-01", "buy", "abc", "100", "T1"),
        _row("RELIANCE", "2025-04-01", "hold", "1", "100", "T2"),
        _row("RELIANCE", "2025-04-01", "buy", "1.5", "100", "T3"),
        _row("RELIANCE", "2025-04-01", "buy", "1", "-4", "T4"),
        _row("RELIANCE", "2025-04-01", "buy", "1", "100", "1.2E+07"),
        _row("NIFTY25APRFUT", "2025-04-01", "buy", "50", "22000", "T6", exchange="NFO"),
        _row("RELIANCE", "2025-04-01", "buy", "1", "100", "T7", exchange="LSE"),
    )
    parsed = parse_tradebook(body, today=TODAY)
    got = [(p.row, p.kind, p.field) for p in parsed.problems]
    assert got == [
        (2, "rejected", "quantity"),
        (3, "rejected", "side"),
        (4, "rejected", "quantity"),
        (5, "rejected", "price"),
        (6, "rejected", "trade id"),
        (7, "segment", "segment"),
        (8, "rejected", "exchange"),
    ]
    for p in parsed.problems:
        for value in ("abc", "hold", "1.5", "-4", "1.2E+07", "NIFTY25APRFUT", "LSE"):
            assert value not in p.reason
    assert parsed.rows == []


def test_xlsx_and_oversize_files_are_refused(session: Session, client: TestClient) -> None:
    _symbols(session)
    uid = _user(session)
    book = _book(client, uid)
    r = _preview(client, uid, book, b"PK\x03\x04rest-of-a-zip")
    assert r.status_code == 422 and "XLSX" in r.json()["detail"]
    big = b"a" * (MAX_FILE_BYTES + 1)
    assert _preview(client, uid, book, big).status_code == 413
    wrong = client.post(
        f"/v1/books/{book}/imports/preview",
        content=b"{}",
        headers={**_h(uid), "Content-Type": "application/json"},
    )
    assert wrong.status_code == 415


# --- preview and commit --------------------------------------------------------------


def test_preview_reports_problems_and_stores_nothing(session: Session, client: TestClient) -> None:
    _symbols(session)
    uid = _user(session)
    book = _book(client, uid)
    body = _csv(
        _row("RELIANCE", "2025-04-01", "buy", "10", "1200.50", "T100"),
        _row("RELIANCE", "2025-04-01", "buy", "x", "1200.50", "T101"),
        _row("UNKNOWNCO", "2025-04-02", "buy", "5", "50", "T102"),
        _row("BANKNIFTY", "2025-04-02", "buy", "15", "300", "T103", exchange="NFO"),
        _row("TCS", "2025-04-03", "sell", "4", "3500", "T104"),
        _row("RELIANCE", "2025-04-04", "sell", "2", "1250", "T105"),
        _row("RELIANCE", "2025-04-04", "sell", "1", "1250", "T105"),
    )
    r = _preview(client, uid, book, body)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["format"] == "zerodha_tradebook_v1"
    assert out["format_status"] == "unconfirmed"
    assert "header row" in out["format_note"]
    assert out["can_commit"] is True
    assert {c["field"]: c["header"] for c in out["columns"]}["executed_at"] == (
        "order_execution_time"
    )
    counts = out["counts"]
    assert counts == {
        "rows": 7,
        "new": 2,
        "posted": 1,
        "needs_opening_lot": 1,
        "duplicate": 2,
        "unmatched": 1,
        "skipped_segment": 1,
        "rejected": 1,
        "basis_uncertain": 0,
        "intraday_inferred": 0,
    }
    problems = [(p["row"], p["kind"]) for p in out["problems"]]
    assert problems == [
        (3, "rejected"),
        (4, "unmatched"),
        (5, "segment"),
        (6, "needs_opening_lot"),
        (7, "duplicate_in_file"),
        (8, "duplicate_in_file"),
    ]
    unmatched = next(p for p in out["problems"] if p["kind"] == "unmatched")
    assert unmatched["symbol"] == "UNKNOWNCO" and unmatched["exchange"] == "NSE"
    sample = out["sample"]
    assert [s["ticker"] for s in sample] == ["RELIANCE.NS", "TCS.NS"]
    assert sample[0]["executed_at"].startswith("2025-04-01T04:45:00")
    assert Decimal(sample[0]["fees"]) > 0
    assert session.exec(select(BrokerFill)).all() == []
    assert session.exec(select(ImportBatch)).all() == []
    assert _trades(session, book) == []


def test_missing_columns_cannot_commit(session: Session, client: TestClient) -> None:
    _symbols(session)
    uid = _user(session)
    book = _book(client, uid)
    body = _csv("RELIANCE,2025-04-01,10", header="symbol,trade_date,quantity")
    out = _preview(client, uid, book, body).json()
    assert out["can_commit"] is False
    assert out["missing_required"] == ["exchange", "side", "price", "trade_id"]
    assert "Trade type" in out["message"]
    assert _commit(client, uid, book, body).status_code == 422


def test_commit_posts_holdings_only_and_dedupes(session: Session, client: TestClient) -> None:
    _symbols(session)
    uid = _user(session)
    book = _book(client, uid)
    first = _csv(
        _row("RELIANCE", "2025-04-01", "buy", "10", "1200", "T1"),
        _row("RELIANCE", "2025-04-08", "sell", "4", "1300", "T2"),
    )
    preview = _preview(client, uid, book, first).json()
    wrong = _commit(client, uid, book, first, sha="0" * 64)
    assert wrong.status_code == 409 and "not the file you previewed" in wrong.json()["detail"]
    r = _commit(client, uid, book, first, sha=preview["file_sha256"])
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["added"] == 2 and out["batch"]["rows_added"] == 2
    assert out["batch"]["posted"] == 2 and out["batch"]["format_status"] == "unconfirmed"
    assert _positions(session, book) == {"RELIANCE.NS": (Decimal(6), Decimal(1200))}
    buy, sell = _trades(session, book)
    assert sell.realized_pnl == Decimal(400) and sell.avg_cost_at_fill == Decimal(1200)
    assert buy.fees is not None and buy.fee_schedule == "in_equity_delivery_nse"
    portfolio = session.get(Portfolio, book)
    assert portfolio is not None and portfolio.cash_balance == 0
    # Stored: the batch's hash and counts, no file and no file name.
    batch = session.exec(select(ImportBatch)).one()
    assert batch.file_sha256 == preview["file_sha256"]
    assert not hasattr(batch, "file_name")

    again = _commit(client, uid, book, first)
    assert again.status_code == 200 and again.json() == {
        "batch": None,
        "added": 0,
        "counts": again.json()["counts"],
    }
    assert again.json()["counts"]["duplicate"] == 2
    overlap = _csv(
        _row("RELIANCE", "2025-04-08", "sell", "4", "1300", "T2"),
        _row("RELIANCE", "2025-04-09", "sell", "1", "1310", "T3"),
    )
    assert _commit(client, uid, book, overlap).json()["added"] == 1
    assert len(session.exec(select(BrokerFill)).all()) == 3
    assert _positions(session, book)["RELIANCE.NS"][0] == Decimal(5)
    trades = client.get(f"/v1/trades?book={book}", headers=_h(uid)).json()
    assert all(t["fees_estimated"] and t["broker_fill_id"] for t in trades)
    # Imported books still refuse paper trades.
    paper = client.post(
        f"/v1/trades?book={book}",
        json={"ticker": "RELIANCE.NS", "side": "buy", "quantity": "1"},
        headers=_h(uid),
    )
    assert paper.status_code == 409


def test_isin_maps_before_the_symbol(session: Session, client: TestClient) -> None:
    _symbols(session)
    uid = _user(session)
    book = _book(client, uid)
    body = _csv(
        _row("RELIANCE-OLDNAME", "2025-04-01", "buy", "3", "1000", "T1", isin=RELIANCE_ISIN),
        _row("INFY", "2025-04-01", "buy", "2", "1500", "T2", exchange="BSE"),
    )
    out = _preview(client, uid, book, body).json()
    assert [s["ticker"] for s in out["sample"]] == ["RELIANCE.NS", "INFY.BO"]
    _commit(client, uid, book, body)
    fills = session.exec(select(BrokerFill).order_by(col(BrokerFill.id))).all()
    assert [(f.ticker, f.raw_symbol, f.isin) for f in fills] == [
        ("RELIANCE.NS", "RELIANCE-OLDNAME", RELIANCE_ISIN),
        ("INFY.BO", "INFY", None),
    ]
    assert fills[1].fee_lines and _trades(session, book)[1].fee_schedule == (
        "in_equity_delivery_bse"
    )


def test_paper_books_other_users_and_usd_books(session: Session, client: TestClient) -> None:
    _symbols(session)
    uid, other = _user(session), _user(session)
    book = _book(client, uid)
    body = _csv(_row("RELIANCE", "2025-04-01", "buy", "1", "1000", "T1"))
    _commit(client, uid, book, body)
    batch = session.exec(select(ImportBatch)).one()
    for method, path in (
        ("post", f"/v1/books/{book}/imports/preview"),
        ("post", f"/v1/books/{book}/imports/commit?file_sha256={'a' * 64}"),
        ("get", f"/v1/books/{book}/imports"),
        ("delete", f"/v1/books/{book}/imports/{batch.id}"),
        ("delete", f"/v1/books/{book}/opening-lots/1"),
    ):
        kwargs: dict = {"headers": {**_h(other), "Content-Type": "text/csv"}}
        if method == "post":
            kwargs["content"] = body
        r = getattr(client, method)(path, **kwargs)
        assert r.status_code == 404, (path, r.status_code)
    lot = client.post(
        f"/v1/books/{book}/opening-lots",
        json={"ticker": "RELIANCE.NS", "on": "2025-01-01", "quantity": "1", "avg_price": "900"},
        headers=_h(other),
    )
    assert lot.status_code == 404
    paper = client.get("/v1/books", headers=_h(uid)).json()["books"][0]["id"]
    assert _preview(client, uid, paper, body).status_code == 409
    usd = _book(client, uid, base_currency="USD")
    r = _preview(client, uid, usd, body)
    assert r.status_code == 409 and "rupees" in r.json()["detail"]


# --- fees --------------------------------------------------------------------------------


def test_fees_are_estimated_and_same_day_round_trips_are_intraday(
    session: Session, client: TestClient
) -> None:
    _symbols(session)
    uid = _user(session)
    book = _book(client, uid)
    body = _csv(
        _row("TCS", "2025-06-02", "buy", "10", "3400", "T1", time="09:20:00"),
        _row("TCS", "2025-06-02", "sell", "6", "3420", "T2", time="14:00:00"),
        _row("RELIANCE", "2025-06-03", "buy", "5", "1400", "T3"),
    )
    _commit(client, uid, book, body)
    fills = {f.trade_id: f for f in session.exec(select(BrokerFill)).all()}
    assert fills["T1"].product == "mixed" and fills["T2"].product == "intraday"
    assert fills["T3"].product == "delivery"
    assert all(f.fee_source == "estimated" for f in fills.values())
    on = date(2025, 6, 2)
    intra = get_fee_schedule("in_equity_intraday_nse")
    deliv = get_fee_schedule("in_equity_delivery_nse")
    expected_buy = (
        intra.fees(OrderSide.BUY, Decimal(6), Decimal(3400), on=on).total
        + deliv.fees(OrderSide.BUY, Decimal(4), Decimal(3400), on=on).total
    )
    expected_sell = intra.fees(OrderSide.SELL, Decimal(6), Decimal(3420), on=on).total
    assert fills["T1"].fees == expected_buy
    assert fills["T2"].fees == expected_sell
    expected = deliv.fees(OrderSide.BUY, Decimal(5), Decimal(1400), on=date(2025, 6, 3)).total
    assert fills["T3"].fees == expected
    labels = [line["label"] for line in fills["T1"].fee_lines or []]
    assert any(label.startswith("Intraday") for label in labels)
    assert any(label.startswith("Delivery") for label in labels)
    out = _preview(client, uid, book, body).json()
    assert out["counts"]["duplicate"] == 3


def test_delivery_sells_pay_dp_once_a_day(session: Session, client: TestClient) -> None:
    _symbols(session)
    uid = _user(session)
    book = _book(client, uid)
    body = _csv(
        _row("RELIANCE", "2025-06-02", "buy", "10", "1400", "T1"),
        _row("RELIANCE", "2025-06-05", "sell", "3", "1450", "T2", time="10:00:00"),
        _row("RELIANCE", "2025-06-05", "sell", "3", "1450", "T3", time="11:00:00"),
    )
    _commit(client, uid, book, body)
    fills = {f.trade_id: f for f in session.exec(select(BrokerFill)).all()}
    dp = [
        [line for line in (fills[t].fee_lines or []) if line["key"] == "dp_charge"]
        for t in ("T2", "T3")
    ]
    assert len(dp[0]) == 1 and dp[1] == []


# --- splits, opening lots, batch delete ------------------------------------------------


def _split(session: Session, ticker: str, ex: date, ratio_to: int) -> None:
    session.add(
        CorporateAction(
            ticker=ticker,
            kind="split",
            ex_date=ex,
            ratio_from=Decimal(1),
            ratio_to=Decimal(ratio_to),
            source="test",
        )
    )
    session.commit()


def _bar(session: Session, ticker: str, day: date, low: str, high: str) -> None:
    session.add(
        PriceBar(
            ticker=ticker,
            ts=datetime.combine(day, datetime.min.time()),
            interval="1d",
            open=Decimal(low),
            high=Decimal(high),
            low=Decimal(low),
            close=Decimal(high),
            volume=1000,
            source="test",
        )
    )
    session.commit()


def test_fills_before_a_split_are_restated_to_split_adjusted_bars(
    session: Session, client: TestClient
) -> None:
    _symbols(session)
    _split(session, "TCS.NS", date(2025, 7, 1), 2)
    # Split-adjusted bars: 3400 before the split reads 1700.
    _bar(session, "TCS.NS", date(2025, 6, 2), "1690", "1710")
    _bar(session, "RELIANCE.NS", date(2025, 6, 2), "1390", "1410")
    uid = _user(session)
    book = _book(client, uid)
    body = _csv(
        _row("TCS", "2025-06-02", "buy", "10", "3400", "T1"),
        _row("TCS", "2025-07-10", "sell", "5", "1800", "T2"),
        # As traded 2800 against a 1400 bar: an unrecorded bonus.
        _row("RELIANCE", "2025-06-02", "buy", "4", "2800", "T3"),
    )
    out = _preview(client, uid, book, body).json()
    first = out["sample"][0]
    assert Decimal(first["restated_quantity"]) == 20 and Decimal(first["restated_price"]) == 1700
    assert out["counts"]["basis_uncertain"] == 1
    assert [p["row"] for p in out["problems"] if p["kind"] == "basis_uncertain"] == [4]
    _commit(client, uid, book, body)
    fills = {f.trade_id: f for f in session.exec(select(BrokerFill)).all()}
    assert (fills["T1"].quantity, fills["T1"].price) == (Decimal(10), Decimal(3400))
    assert fills["T3"].basis_uncertain and not fills["T1"].basis_uncertain
    assert _positions(session, book)["TCS.NS"] == (Decimal(15), Decimal(1700))
    sell = next(t for t in _trades(session, book) if t.side.value == "sell")
    assert sell.realized_pnl == Decimal(500)  # (1800 - 1700) x 5


def test_a_split_recorded_later_rebuilds_the_imported_book(
    session: Session, client: TestClient
) -> None:
    _symbols(session)
    uid = _user(session)
    book = _book(client, uid)
    _commit(client, uid, book, _csv(_row("TCS", "2025-06-02", "buy", "10", "3400", "T1")))
    _split(session, "TCS.NS", date(2025, 7, 1), 2)
    assert apply_due_splits(session, now=datetime(2025, 7, 2, 2, tzinfo=UTC)).users_rebased == 1
    session.commit()
    assert _positions(session, book) == {"TCS.NS": (Decimal(20), Decimal(1700))}
    assert apply_due_splits(session, now=datetime(2025, 7, 2, 2, tzinfo=UTC)).users_rebased == 0
    assert _positions(session, book) == {"TCS.NS": (Decimal(20), Decimal(1700))}


def test_sells_before_any_buy_wait_for_an_opening_lot(session: Session, client: TestClient) -> None:
    _symbols(session)
    uid = _user(session)
    book = _book(client, uid)
    body = _csv(
        _row("RELIANCE", "2025-05-02", "sell", "8", "1500", "T1"),
        _row("RELIANCE", "2025-05-03", "buy", "2", "1450", "T2"),
    )
    _commit(client, uid, book, body)
    assert _positions(session, book) == {"RELIANCE.NS": (Decimal(2), Decimal(1450))}
    status = client.get(f"/v1/books/{book}/imports", headers=_h(uid)).json()
    assert status["needs_opening_lot"] == [
        {
            "ticker": "RELIANCE.NS",
            "fills": 1,
            "first_sell_at": "2025-05-02T04:45:00",
            "short_by": "8.000000",
        }
    ]
    future = client.post(
        f"/v1/books/{book}/opening-lots",
        json={
            "ticker": "RELIANCE.NS",
            "on": (date.today() + timedelta(days=3)).isoformat(),
            "quantity": "10",
            "avg_price": "1000",
        },
        headers=_h(uid),
    )
    assert future.status_code == 422
    lot = client.post(
        f"/v1/books/{book}/opening-lots",
        json={"ticker": "reliance.ns", "on": "2025-04-01", "quantity": "10", "avg_price": "1000"},
        headers=_h(uid),
    )
    assert lot.status_code == 201, lot.text
    assert _positions(session, book) == {"RELIANCE.NS": (Decimal(4), Decimal(1225))}
    sell = next(t for t in _trades(session, book) if t.side.value == "sell")
    assert sell.realized_pnl == Decimal(4000)
    opening = _trades(session, book)[0]
    assert opening.fees is None and opening.price == Decimal(1000)
    status = client.get(f"/v1/books/{book}/imports", headers=_h(uid)).json()
    assert status["needs_opening_lot"] == [] and len(status["opening_lots"]) == 1
    gone = client.delete(f"/v1/books/{book}/opening-lots/{lot.json()['id']}", headers=_h(uid))
    assert gone.status_code == 204
    assert _positions(session, book) == {"RELIANCE.NS": (Decimal(2), Decimal(1450))}


def test_deleting_a_batch_restores_the_book(session: Session, client: TestClient) -> None:
    _symbols(session)
    uid = _user(session)
    book = _book(client, uid)
    _commit(client, uid, book, _csv(_row("RELIANCE", "2025-04-01", "buy", "10", "1200", "T1")))
    before = _positions(session, book)
    second = _commit(
        client,
        uid,
        book,
        _csv(
            _row("RELIANCE", "2025-04-05", "buy", "10", "1300", "T2"),
            _row("TCS", "2025-04-05", "buy", "1", "3000", "T3"),
        ),
    ).json()["batch"]
    # A third file's sell needs the second file's shares.
    _commit(client, uid, book, _csv(_row("RELIANCE", "2025-04-09", "sell", "15", "1400", "T4")))
    assert _positions(session, book)["RELIANCE.NS"] == (Decimal(5), Decimal(1250))
    listed = client.get(f"/v1/books/{book}/imports", headers=_h(uid)).json()
    assert [b["rows_added"] for b in listed["batches"]] == [1, 2, 1]
    r = client.delete(f"/v1/books/{book}/imports/{second['id']}", headers=_h(uid))
    assert r.status_code == 204
    assert _positions(session, book) == before
    fills = session.exec(select(BrokerFill)).all()
    assert sorted(f.trade_id or "" for f in fills) == ["T1", "T4"]
    t4 = next(f for f in fills if f.trade_id == "T4")
    assert t4.status == "needs_opening_lot"
    assert [t.broker_fill_id for t in _trades(session, book)] == [
        next(f.id for f in fills if f.trade_id == "T1")
    ]
    assert (
        client.delete(f"/v1/books/{book}/imports/{second['id']}", headers=_h(uid)).status_code
        == 404
    )


def test_deleting_the_book_removes_its_imports(session: Session, client: TestClient) -> None:
    _symbols(session)
    uid = _user(session)
    book = _book(client, uid)
    _commit(client, uid, book, _csv(_row("RELIANCE", "2025-04-01", "buy", "10", "1200", "T1")))
    assert (
        client.patch(f"/v1/books/{book}", json={"archived": True}, headers=_h(uid)).status_code
        == 200
    )
    assert client.delete(f"/v1/books/{book}", headers=_h(uid)).status_code == 204
    assert session.exec(select(BrokerFill)).all() == []
    assert session.exec(select(ImportBatch)).all() == []
    assert session.exec(select(Trade)).all() == []


# --- plans and the combined view ------------------------------------------------------


def _plan(client: TestClient, uid: int, book: int, **extra) -> dict:
    body = {
        "ticker": "RELIANCE.NS",
        "planned_entry": "1200",
        "planned_stop": "1100",
        "planned_size": "10",
        **extra,
    }
    r = client.post(f"/v1/plans?book={book}", json=body, headers=_h(uid))
    assert r.status_code == 201, r.text
    return r.json()


def test_an_imported_buy_locks_a_plan_written_before_it(
    session: Session, client: TestClient
) -> None:
    _symbols(session)
    uid = _user(session)
    book = _book(client, uid)
    plan = _plan(client, uid, book)
    assert plan["source"] == "imported"
    row = session.get(TradePlan, plan["id"])
    assert row is not None
    row.created_at = datetime(2025, 3, 31, 12)
    session.add(row)
    session.commit()
    body = _csv(
        _row("RELIANCE", "2025-04-01", "buy", "6", "1200", "T1", time="09:30:00"),
        _row("RELIANCE", "2025-04-02", "buy", "4", "1210", "T2"),
        _row("RELIANCE", "2025-04-10", "sell", "10", "1300", "T3"),
    )
    _commit(client, uid, book, body)
    session.expire_all()
    row = session.get(TradePlan, plan["id"])
    assert row is not None
    assert row.locked_at == datetime(2025, 4, 1, 4, 0) and not row.written_after_entry
    assert row.status == "closed"  # the position went back to zero
    buys = [t for t in _trades(session, book) if t.side.value == "buy"]
    assert [t.trade_plan_id for t in buys] == [plan["id"]] * 2
    edit = client.patch(f"/v1/plans/{plan['id']}", json={"planned_stop": "1000"}, headers=_h(uid))
    assert edit.status_code == 409


def test_a_plan_written_after_the_fill_is_labelled_not_locked(
    session: Session, client: TestClient
) -> None:
    _symbols(session)
    uid = _user(session)
    book = _book(client, uid)
    early = _plan(client, uid, book)  # written now, after the 2025 fill
    _commit(client, uid, book, _csv(_row("RELIANCE", "2025-04-01", "buy", "6", "1200", "T1")))
    session.expire_all()
    row = session.get(TradePlan, early["id"])
    assert row is not None and row.status == "open" and row.first_fill_at is None
    assert client.delete(f"/v1/plans/{early['id']}", headers=_h(uid)).status_code == 204
    linked = _plan(client, uid, book, link_open_position=True)
    assert linked["written_after_entry"] is True and linked["locked_at"] is None
    # A rebuild (another import) keeps the link and the label.
    _commit(client, uid, book, _csv(_row("RELIANCE", "2025-04-03", "buy", "1", "1210", "T2")))
    session.expire_all()
    row = session.get(TradePlan, linked["id"])
    assert row is not None and row.written_after_entry and row.locked_at is None
    assert all(t.trade_plan_id == linked["id"] for t in _trades(session, book))


def test_deleting_the_batch_closes_the_plan_and_keeps_it_frozen(
    session: Session, client: TestClient
) -> None:
    _symbols(session)
    uid = _user(session)
    book = _book(client, uid)
    plan = _plan(client, uid, book)
    row = session.get(TradePlan, plan["id"])
    assert row is not None
    row.created_at = datetime(2025, 3, 1)
    session.add(row)
    session.commit()
    batch = _commit(
        client, uid, book, _csv(_row("RELIANCE", "2025-04-01", "buy", "6", "1200", "T1"))
    ).json()["batch"]
    client.delete(f"/v1/books/{book}/imports/{batch['id']}", headers=_h(uid))
    session.expire_all()
    row = session.get(TradePlan, plan["id"])
    assert row is not None and row.status == "closed" and row.frozen


def test_imported_buys_and_sells_are_outside_flows(session: Session, client: TestClient) -> None:
    _symbols(session)
    uid = _user(session)
    book = _book(client, uid)
    _commit(
        client,
        uid,
        book,
        _csv(
            _row("RELIANCE", "2025-04-01", "buy", "10", "1200", "T1"),
            _row("RELIANCE", "2025-04-08", "sell", "4", "1300", "T2"),
        ),
    )
    portfolio = session.get(Portfolio, book)
    assert portfolio is not None
    buy, sell = _trades(session, book)
    assert imported_flows(session, portfolio) == [
        (date(2025, 4, 1), Decimal(12000) + (buy.fees or 0)),
        (date(2025, 4, 8), -(Decimal(5200) - (sell.fees or 0))),
    ]
    combined = client.get("/v1/portfolio/history?book=all", headers=_h(uid))
    assert combined.status_code == 200


# --- privacy ---------------------------------------------------------------------------------


def test_no_cell_value_reaches_the_logs(
    session: Session, client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    _symbols(session)
    uid = _user(session)
    book = _book(client, uid)
    body = _csv(
        _row(
            "RELIANCE", "2025-04-01", "buy", "17", "1234.55", "TRD99887766", order_id="ORD55443322"
        ),
        _row("RELIANCE", "2025-04-02", "buy", "seventeen", "1234.55", "TRD99887767"),
        _row("NOSUCHCO", "2025-04-02", "buy", "3", "77.77", "TRD99887768"),
        _row("RELIANCE", "2025-04-03", "sell", "999", "4321.12", "TRD99887769"),
    )
    with caplog.at_level(logging.DEBUG):
        _preview(client, uid, book, body)
        batch = _commit(client, uid, book, body).json()["batch"]
        client.get(f"/v1/books/{book}/imports", headers=_h(uid))
        client.delete(f"/v1/books/{book}/imports/{batch['id']}", headers=_h(uid))
    text = "\n".join(r.getMessage() + " " + repr(r.args) for r in caplog.records)
    for value in (
        "TRD99887766",
        "ORD55443322",
        "1234.55",
        "seventeen",
        "NOSUCHCO",
        "77.77",
        "4321.12",
        "999",
    ):
        assert value not in text
    assert session.exec(select(BrokerFill)).all() == []


def test_sentry_events_from_import_routes_lose_the_body() -> None:
    event = {
        "request": {
            "url": "http://api/v1/books/3/imports/commit",
            "data": "symbol,price\nRELIANCE,1234.55",
            "query_string": "file_sha256=abc",
        },
        "exception": {"values": [{"stacktrace": {"frames": [{"vars": {"body": "x"}}]}}]},
    }
    out = scrub_event(event)
    assert "data" not in out["request"] and "query_string" not in out["request"]
    assert "vars" not in out["exception"]["values"][0]["stacktrace"]["frames"][0]
    other = {"request": {"url": "http://api/v1/symbols", "data": "kept"}}
    assert scrub_event(other)["request"]["data"] == "kept"
