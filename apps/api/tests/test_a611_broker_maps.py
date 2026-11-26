"""A6.11: broker column maps (Dhan, Fyers, Upstox, Angel One, Groww), the
user's own map ("Map columns yourself", INR and USD books) and the basket
handoff endpoint.

Every fixture is synthetic: invented symbols' trades, ids, prices and dates.
No real tradebook, and no header row copied from a real file, enters the
repository (the maps themselves are unconfirmed).
"""

from __future__ import annotations

import logging
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from jose import jwt as jose_jwt
from sqlmodel import Session, col, select

from stockviz.main import app
from stockviz.models import BrokerFill, ImportBatch, Position, Symbol, Trade, User
from stockviz.services.imports import columns
from stockviz.services.imports.columns import detect_map, match_headers
from stockviz.services.imports.parse import parse_tradebook
from stockviz.settings import Settings, get_settings
from tests.test_imports import TODAY

SECRET = get_settings().internal_api_token


def _h(user_id: int) -> dict[str, str]:
    token = jose_jwt.encode({"sub": str(user_id)}, SECRET, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


def _user(session: Session) -> int:
    user = User(email=f"{uuid4().hex}@stockviz.dev", name="Maps")
    session.add(user)
    session.commit()
    session.refresh(user)
    assert user.id is not None
    return user.id


def _symbols(session: Session) -> None:
    for ticker, currency in (
        ("RELIANCE.NS", "INR"),
        ("TCS.NS", "INR"),
        ("INFY.BO", "INR"),
        ("AAPL", "USD"),
        ("BRK-B", "USD"),
    ):
        if session.get(Symbol, ticker) is None:
            session.add(Symbol(ticker=ticker, name=ticker, currency=currency))
    session.commit()


def _book(client: TestClient, uid: int, **body) -> int:
    body.setdefault("name", f"Book {uuid4().hex[:6]}")
    body.setdefault("kind", "imported")
    body.setdefault("base_currency", "INR")
    r = client.post("/v1/books", json=body, headers=_h(uid))
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _csv(header: str, *rows: str) -> bytes:
    return ("\n".join([header, *rows]) + "\n").encode()


def _post(client: TestClient, uid: int, book: int, body: bytes, step: str = "preview", **q):
    query = "&".join(f"{k}={v}" for k, v in q.items())
    return client.post(
        f"/v1/books/{book}/imports/{step}" + (f"?{query}" if query else ""),
        content=body,
        headers={**_h(uid), "Content-Type": "text/csv"},
    )


def _commit(client: TestClient, uid: int, book: int, body: bytes, **q):
    preview = _post(client, uid, book, body, **q)
    assert preview.status_code == 200, preview.text
    return _post(client, uid, book, body, "commit", file_sha256=preview.json()["file_sha256"], **q)


# --- one synthetic header row and row per broker map ---------------------------------------

FILES: dict[str, tuple[str, str]] = {
    "dhan_tradebook_v1": (
        "Trading Symbol,ISIN,Exchange Segment,Instrument,Transaction Type,Traded Quantity,"
        "Traded Price,Exchange Trade ID,Order ID,Exchange Time",
        "RELIANCE,,NSE_EQ,EQUITY,BUY,4,1200.50,DH1001,DO1,2025-04-01 10:15:00",
    ),
    "fyers_tradebook_v1": (
        "Name,Date and time,Side,Product type,Qty,Traded price,Total value,Segment,"
        "Exchange order ID,FYERS order ID",
        "NSE:RELIANCE-EQ,2025-04-01 10:15:00,BUY,CNC,4,1200.50,4802,CM,EX1,FY1",
    ),
    "upstox_tradebook_v1": (
        "Scrip Name,Scrip Code,Trade Date,Exchange,Segment,Side,Quantity,Price,Trade Num,"
        "Order No,Trade Time",
        "RELIANCE,500325,2025-04-01,NSE,EQ,Buy,4,1200.50,UP1001,UO1,10:15:00",
    ),
    "angelone_tradebook_v1": (
        "Symbol,Exchange,Product,Buy/Sell,Filled Shares,Fill Price,Fill ID,Order ID,Fill Time",
        "RELIANCE,NSE,DELIVERY,BUY,4,1200.50,AN1001,AO1,2025-04-01 10:15:00",
    ),
    "groww_orders_v1": (
        "Stock name,ISIN,Type,Executed quantity,Price,Exchange,Exchange Order Id,"
        "Execution date and time,Order status",
        "RELIANCE,,BUY,4,1200.50,NSE,GO1,2025-04-01 10:15:00,Executed",
    ),
}


@pytest.mark.parametrize("name", sorted(FILES))
def test_each_map_is_detected_from_its_header(name: str) -> None:
    header, _row = FILES[name]
    found = detect_map(header.split(","))
    assert found.how == "header"
    assert found.column_map.name == name
    assert found.column_map.status == "unconfirmed"
    assert found.column_map.source  # every map cites what it is built from


@pytest.mark.parametrize("name", sorted(FILES))
def test_each_map_parses_its_synthetic_row(name: str) -> None:
    header, row = FILES[name]
    parsed = parse_tradebook(_csv(header, row), today=TODAY, column_map=columns.MAPS[name])
    assert parsed.problems == []
    [r] = parsed.rows
    assert (r.symbol, r.exchange, r.side, r.quantity, r.price) == (
        "RELIANCE",
        "NSE",
        "buy",
        Decimal(4),
        Decimal("1200.50"),
    )
    assert r.trade_date.isoformat() == "2025-04-01"


@pytest.mark.parametrize("name", sorted(FILES))
def test_each_map_rejects_a_missing_required_column_by_name(name: str) -> None:
    m = columns.MAPS[name]
    header, _row = FILES[name]
    headers = header.split(",")
    for spec in m.fields:
        if not spec.required or spec.required_unless:
            continue
        kept = [h for h in headers if columns.normalise_header(h) not in spec.aliases]
        match = match_headers(kept, m)
        assert spec.field in match.missing_required, (name, spec.field)


def test_a_missing_column_is_named_in_the_preview(session: Session, client: TestClient) -> None:
    _symbols(session)
    uid = _user(session)
    book = _book(client, uid, broker="dhan")
    header = "Trading Symbol,Exchange Segment,Transaction Type,Traded Price,Exchange Trade ID"
    body = _csv(header, "RELIANCE,NSE_EQ,BUY,1200.50,DH1")
    out = _post(client, uid, book, body).json()
    assert out["format"] == "dhan_tradebook_v1"
    assert out["detected"] == "fallback"
    assert out["missing_required"] == ["trade_date", "quantity"]
    assert "Traded quantity" in out["message"] and out["can_commit"] is False
    assert out["headers"] == header.split(",")
    sha = out["file_sha256"]
    assert _post(client, uid, book, body, "commit", file_sha256=sha).status_code == 422


def test_preview_shows_which_map_and_the_user_can_pick(
    session: Session, client: TestClient
) -> None:
    _symbols(session)
    uid = _user(session)
    book = _book(client, uid)
    header, row = FILES["upstox_tradebook_v1"]
    out = _post(client, uid, book, _csv(header, row)).json()
    assert (out["format"], out["format_label"], out["detected"]) == (
        "upstox_tradebook_v1",
        "Upstox trade report",
        "header",
    )
    assert out["broker"] == "upstox" and out["format_status"] == "unconfirmed"
    chosen = _post(client, uid, book, _csv(header, row), map="upstox_tradebook_v1").json()
    assert chosen["detected"] == "chosen"
    assert _post(client, uid, book, _csv(header, row), map="nope").status_code == 422
    # A Zerodha file chosen as Dhan's is read with Dhan's map and fails by name.
    z = _csv(
        "symbol,trade_date,exchange,trade_type,quantity,price,trade_id",
        "RELIANCE,2025-04-01,NSE,buy,1,10,T1",
    )
    out = _post(client, uid, book, z, map="dhan_tradebook_v1").json()
    assert out["format"] == "dhan_tradebook_v1" and "side" in out["missing_required"]


def test_dhan_compound_segment_and_fno_skipped(session: Session, client: TestClient) -> None:
    _symbols(session)
    uid = _user(session)
    book = _book(client, uid, broker="dhan")
    header, row = FILES["dhan_tradebook_v1"]
    body = _csv(
        header,
        row,
        "NIFTY-Dec2025-24000-CE,,NSE_FNO,OPTIDX,BUY,75,10.5,DH1002,DO2,2025-04-01 10:16:00",
        "GOLDM,,MCX_COMM,FUTCOM,SELL,1,70000,DH1003,DO3,2025-04-01 10:17:00",
        "TCS,,BSE_EQ,EQUITY,BUY,2,3500,DH1004,DO4,2025-04-01 10:18:00",
    )
    r = _commit(client, uid, book, body)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["counts"]["skipped_segment"] == 2
    assert out["counts"]["unmatched"] == 1  # TCS.BO is not a StockViz symbol here
    assert out["batch"]["broker"] == "dhan" and out["batch"]["column_map"] == "dhan_tradebook_v1"
    fills = session.exec(select(BrokerFill).where(col(BrokerFill.portfolio_id) == book)).all()
    assert [(f.ticker, f.broker, f.exchange, f.segment) for f in fills] == [
        ("RELIANCE.NS", "dhan", "NSE", "EQUITY")
    ]


def test_fyers_symbol_prefix_and_derived_trade_ids(session: Session, client: TestClient) -> None:
    _symbols(session)
    uid = _user(session)
    book = _book(client, uid, broker="fyers")
    header, row = FILES["fyers_tradebook_v1"]
    same = row  # two identical fills of one order are two trades
    body = _csv(
        header,
        row,
        same,
        "INFY,2025-04-01 10:20:00,BUY,CNC,1,1500,1500,CM,EX2,FY2",  # no exchange anywhere
        "NSE:NIFTY25APRFUT,2025-04-01 10:21:00,SELL,MARGIN,50,22000,1,FO,EX3,FY3",
    )
    first = _commit(client, uid, book, body)
    assert first.status_code == 200, first.text
    counts = first.json()["counts"]
    assert (counts["new"], counts["rejected"], counts["skipped_segment"]) == (2, 1, 1)
    ids = session.exec(
        select(BrokerFill.trade_id).where(col(BrokerFill.portfolio_id) == book)
    ).all()
    assert len(set(ids)) == 2 and all(i and i.startswith("sv-") for i in ids)
    assert session.exec(select(Position).where(col(Position.portfolio_id) == book)).one().quantity
    # The same file again: every derived id repeats, so nothing is new.
    again = _post(client, uid, book, body).json()
    assert again["counts"]["new"] == 0 and again["counts"]["duplicate"] == 2
    problem = next(p for p in again["problems"] if p["kind"] == "rejected")
    assert problem["field"] == "exchange" and "NSE:" in problem["reason"]


def test_groww_leaves_out_orders_that_did_not_execute(session: Session, client: TestClient) -> None:
    _symbols(session)
    uid = _user(session)
    book = _book(client, uid, broker="groww")
    header, row = FILES["groww_orders_v1"]
    body = _csv(header, row, "TCS,,BUY,1,3500,NSE,GO2,2025-04-01 11:00:00,Cancelled")
    out = _post(client, uid, book, body).json()
    assert out["counts"]["new"] == 1 and out["counts"]["not_executed"] == 1
    assert [p["kind"] for p in out["problems"]] == ["not_executed"]


def test_a_broker_map_needs_an_inr_book(session: Session, client: TestClient) -> None:
    _symbols(session)
    uid = _user(session)
    book = _book(client, uid, base_currency="USD", broker="other")
    header, row = FILES["angelone_tradebook_v1"]
    r = _post(client, uid, book, _csv(header, row))
    assert r.status_code == 409 and "Angel One" in r.json()["detail"]


# --- "Map columns yourself" ------------------------------------------------------------------


def _save_map(client: TestClient, uid: int, **body):
    return client.post("/v1/import-maps", json=body, headers=_h(uid))


def test_saved_map_validation(session: Session, client: TestClient) -> None:
    uid = _user(session)
    missing = _save_map(client, uid, name="Mine", mapping={"symbol": "Ticker"})
    assert missing.status_code == 422
    assert "Quantity" in missing.json()["detail"] and "Trade date" in missing.json()["detail"]
    twice = _save_map(
        client,
        uid,
        name="Mine",
        mapping={
            "symbol": "Ticker",
            "side": "Action",
            "quantity": "Qty",
            "price": "Qty",
            "trade_date": "Date",
        },
    )
    assert twice.status_code == 422 and "same header" in twice.json()["detail"]
    bad = _save_map(client, uid, name="Mine", mapping={"colour": "x"})
    assert bad.status_code == 422


def test_saved_map_reads_an_indian_file(session: Session, client: TestClient) -> None:
    _symbols(session)
    uid = _user(session)
    other = _user(session)
    book = _book(client, uid, broker="other")
    saved = _save_map(
        client,
        uid,
        name="My Broker",
        mapping={
            "trade_date": "Dt",
            "symbol": "Scrip",
            "side": "B/S",
            "quantity": "Units",
            "price": "Rate",
            "trade_id": "Ref",
        },
        default_exchange="NSE",
        date_order="day_first",
    )
    assert saved.status_code == 201, saved.text
    map_id = saved.json()["id"]
    body = _csv("Dt,Scrip,B/S,Units,Rate,Ref", "03/04/2025,RELIANCE,B,5,1200,R1")
    out = _post(client, uid, book, body, custom_map=map_id).json()
    assert (out["format"], out["format_status"], out["detected"]) == (
        f"custom_{map_id}",
        "custom",
        "saved",
    )
    assert out["sample"][0]["executed_at"].startswith("2025-04-02T18:30:00")  # 3 Apr IST
    r = _commit(client, uid, book, body, custom_map=map_id)
    assert r.status_code == 200 and r.json()["batch"]["format_status"] == "custom"
    assert r.json()["batch"]["broker"] == "other"
    # Another user can't read with it, list it or delete it.
    other_book = _book(client, other, broker="other")
    assert _post(client, other, other_book, body, custom_map=map_id).status_code == 404
    assert client.get("/v1/import-maps", headers=_h(other)).json() == []
    assert client.delete(f"/v1/import-maps/{map_id}", headers=_h(other)).status_code == 404
    listed = client.get(f"/v1/books/{book}/imports", headers=_h(uid)).json()
    assert [m["name"] for m in listed["saved_maps"]] == ["My Broker"]
    assert {m["name"] for m in listed["maps"]} == set(columns.MAPS)
    assert client.delete(f"/v1/import-maps/{map_id}", headers=_h(uid)).status_code == 204


def test_saved_map_reads_a_us_broker_into_a_usd_book(session: Session, client: TestClient) -> None:
    _symbols(session)
    uid = _user(session)
    book = _book(client, uid, base_currency="USD", broker="other")
    map_id = _save_map(
        client,
        uid,
        name="US Broker",
        mapping={
            "executed_at": "Date/Time",
            "symbol": "Symbol",
            "exchange": "Exchange",
            "side": "Action",
            "quantity": "Quantity",
            "price": "Price",
        },
    ).json()["id"]
    body = _csv(
        "Date/Time,Symbol,Exchange,Action,Quantity,Price",
        "2025-04-01 09:45:00,AAPL,NASDAQ,Bought,1.5,200.25",
        "2025-04-01 10:00:00,BRK.B,NYSE,Bought,2,480",
        "2025-04-01 10:05:00,AAPL 250418C00200000,,Bought,1,5.10",
        "2025-04-02 15:30:00,AAPL,NASDAQ,Sold,0.5,210.25",
        "2025-04-02 15:31:00,RELIANCE,NSE,Bought,1,1200",
    )
    r = _commit(client, uid, book, body, custom_map=map_id)
    assert r.status_code == 200, r.text
    counts = r.json()["counts"]
    assert (counts["new"], counts["skipped_segment"], counts["rejected"]) == (3, 1, 1)
    session.expire_all()
    positions = {
        p.ticker: p.quantity
        for p in session.exec(select(Position).where(col(Position.portfolio_id) == book)).all()
    }
    assert positions == {"AAPL": Decimal(1), "BRK-B": Decimal(2)}
    trades = session.exec(select(Trade).where(col(Trade.portfolio_id) == book)).all()
    assert all(t.fees == 0 for t in trades)
    first = min(trades, key=lambda t: t.ts)
    assert first.ts.isoformat().startswith("2025-04-01T13:45:00")  # 09:45 New York, EDT
    fills = session.exec(select(BrokerFill).where(col(BrokerFill.portfolio_id) == book)).all()
    assert {f.exchange for f in fills} == {"US"} and all(f.fee_source is None for f in fills)
    # An opening lot in a USD book is a US symbol.
    lot = client.post(
        f"/v1/books/{book}/opening-lots",
        json={"ticker": "AAPL", "on": "2025-01-02", "quantity": "1", "avg_price": "150"},
        headers=_h(uid),
    )
    assert lot.status_code == 201, lot.text
    indian = client.post(
        f"/v1/books/{book}/opening-lots",
        json={"ticker": "TCS.NS", "on": "2025-01-02", "quantity": "1", "avg_price": "150"},
        headers=_h(uid),
    )
    assert indian.status_code == 422
    # A broker map's file is refused in this book; the Zerodha default too.
    assert _post(client, uid, book, body).status_code == 409


def test_no_cell_value_reaches_the_logs(
    session: Session, client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    _symbols(session)
    uid = _user(session)
    book = _book(client, uid, broker="fyers")
    header, _row = FILES["fyers_tradebook_v1"]
    body = _csv(
        header,
        "NSE:RELIANCE-EQ,2025-04-01 10:15:00,BUY,CNC,7,1357.91,9505.37,CM,EX7788,FY99887766",
        "NSE:NOSUCHCO-EQ,2025-04-01 10:16:00,BUY,CNC,3,24.68,74.04,CM,EX7789,FY99887767",
        "NSE:RELIANCE-EQ,2025-04-01 10:17:00,BUY,CNC,lots,1357.91,1,CM,EX7790,FY99887768",
    )
    with caplog.at_level(logging.DEBUG):
        _post(client, uid, book, body)
        _commit(client, uid, book, body)
        uid_map = _save_map(
            client,
            uid,
            name="Secret Headers",
            mapping={"symbol": "Name", "side": "Side", "quantity": "Qty", "price": "Px",
                     "executed_at": "Date and time"},
        )  # fmt: skip
        assert uid_map.status_code == 201
        _post(client, uid, book, body, custom_map=uid_map.json()["id"])
    text = "\n".join(r.getMessage() + " " + repr(r.args) for r in caplog.records)
    for value in ("1357.91", "9505.37", "FY99887766", "EX7788", "NOSUCHCO", "24.68", "lots"):
        assert value not in text


# --- basket handoff ---------------------------------------------------------------------------


def _settings(key: str) -> Settings:
    return get_settings().model_copy(
        update={"kite_api_key": key, "kite_api_secret": "app-secret-never-sent"}
    )


def test_basket_handoff_is_off_without_kite_api_key(session: Session, client: TestClient) -> None:
    uid = _user(session)
    app.dependency_overrides[get_settings] = lambda: _settings("")
    try:
        out = client.get("/v1/broker/basket", headers=_h(uid)).json()
    finally:
        app.dependency_overrides.pop(get_settings, None)
    assert out == {
        "kite_basket": False,
        "kite_api_key": None,
        "kite_basket_url": None,
        "exports": ["csv", "json"],
    }


def test_basket_handoff_with_kite_api_key_never_returns_the_secret(
    session: Session, client: TestClient
) -> None:
    uid = _user(session)
    app.dependency_overrides[get_settings] = lambda: _settings("publicappkey123")
    try:
        r = client.get("/v1/broker/basket", headers=_h(uid))
        anonymous = client.get("/v1/broker/basket")
    finally:
        app.dependency_overrides.pop(get_settings, None)
    out = r.json()
    assert out["kite_basket"] is True and out["kite_api_key"] == "publicappkey123"
    assert out["kite_basket_url"] == "https://kite.zerodha.com/connect/basket"
    assert "app-secret-never-sent" not in r.text
    assert anonymous.status_code == 401


def test_books_take_the_new_brokers(session: Session, client: TestClient) -> None:
    uid = _user(session)
    for broker in ("dhan", "fyers", "upstox", "angelone", "groww", "other"):
        _book(client, uid, broker=broker)
    r = client.post(
        "/v1/books",
        json={"name": "Bad", "kind": "imported", "base_currency": "INR", "broker": "robinhood"},
        headers=_h(uid),
    )
    assert r.status_code == 422
    assert session.exec(select(ImportBatch)).all() == []
