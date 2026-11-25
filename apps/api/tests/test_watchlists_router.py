"""A2.5 (M4.6): many watchlists, notes, tags, column sets, bulk add.

HTTP-level, with real JWTs against the in-memory SQLite engine, like
``test_watchlist_router.py`` (which still covers the old default-list routes).
"""

from __future__ import annotations

import typing
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from jose import jwt as jose_jwt
from sqlalchemy import event
from sqlmodel import Session

from stockviz.models import DataFile, PriceBar, Symbol, SymbolMetrics, User
from stockviz.models.checklist import ChecklistScore
from stockviz.models.eod import EodExtras
from stockviz.models.watchlist import WATCHLIST_COLOURS
from stockviz.schemas import ColumnKey, WatchlistColour
from stockviz.services import watchlists as svc
from stockviz.services.instruments import instrument_ids
from stockviz.settings import get_settings

SECRET = get_settings().internal_api_token


def _headers(user_id: int) -> dict[str, str]:
    token = jose_jwt.encode({"sub": str(user_id)}, SECRET, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


def _user(session: Session, email: str = "lists@stockviz.dev") -> int:
    user = User(email=email, name="Lists")
    session.add(user)
    session.commit()
    session.refresh(user)
    assert user.id is not None
    return user.id


def _symbols(session: Session, *tickers: str, bars: int = 3) -> None:
    for i, t in enumerate(tickers):
        session.add(Symbol(ticker=t, name=f"{t} Inc.", sector="Technology" if i % 2 == 0 else None))
    session.commit()
    for t in tickers:
        for d in range(bars):
            c = Decimal(100 + d)
            session.add(
                PriceBar(
                    ticker=t, ts=datetime(2026, 11, 2) + timedelta(days=d), interval="1d",
                    open=c, high=c, low=c, close=c, volume=1000 * (d + 1), source="test",
                )
            )  # fmt: skip
    session.commit()


def _default(client: TestClient, h: dict[str, str]) -> dict:
    lists = client.get("/v1/watchlists", headers=h).json()
    return next(w for w in lists if w["is_default"])


def test_literals_match_the_allow_lists() -> None:
    assert typing.get_args(WatchlistColour) == WATCHLIST_COLOURS
    assert typing.get_args(ColumnKey) == svc.COLUMN_KEYS
    assert len(svc.COLUMN_KEYS) == svc.MAX_COLUMNS


def test_requires_auth(client: TestClient) -> None:
    assert client.get("/v1/watchlists").status_code == 401
    assert client.post("/v1/watchlists", json={"name": "x"}).status_code == 401
    assert client.get("/v1/watchlists/1/items").status_code == 401
    assert client.get("/v1/column-sets").status_code == 401


def test_first_read_makes_an_empty_default(session: Session, client: TestClient) -> None:
    h = _headers(_user(session))
    lists = client.get("/v1/watchlists", headers=h).json()
    assert len(lists) == 1
    assert lists[0] | {"id": 0, "created_at": ""} == {
        "id": 0, "name": "Default", "colour": "aqua", "position": 0, "is_default": True,
        "column_set_id": None, "item_count": 0, "contains": None, "created_at": "",
    }  # fmt: skip
    # Reading twice makes nothing new.
    assert len(client.get("/v1/watchlists", headers=h).json()) == 1


def test_create_rename_recolour_reorder_delete(session: Session, client: TestClient) -> None:
    h = _headers(_user(session))
    default = _default(client, h)
    r = client.post(
        "/v1/watchlists", json={"name": "  Earnings   watch ", "colour": "amber"}, headers=h
    )
    assert r.status_code == 201
    earnings = r.json()
    assert (earnings["name"], earnings["colour"], earnings["position"]) == (
        "Earnings watch",
        "amber",
        1,
    )
    stage2 = client.post("/v1/watchlists", json={"name": "Stage 2"}, headers=h).json()
    assert stage2["position"] == 2

    # Names are unique per user, ignoring case.
    assert client.post("/v1/watchlists", json={"name": "stage 2"}, headers=h).status_code == 409
    assert (
        client.patch(
            f"/v1/watchlists/{stage2['id']}", json={"name": "EARNINGS WATCH"}, headers=h
        ).status_code
        == 409
    )
    # Colours come from the palette.
    assert (
        client.post("/v1/watchlists", json={"name": "X", "colour": "red"}, headers=h).status_code
        == 422
    )

    r = client.patch(
        f"/v1/watchlists/{stage2['id']}",
        json={"name": "Stage-2 focus", "colour": "violet"},
        headers=h,
    )
    assert (
        r.status_code == 200
        and r.json()["name"] == "Stage-2 focus"
        and r.json()["colour"] == "violet"
    )

    order = [stage2["id"], default["id"], earnings["id"]]
    r = client.post("/v1/watchlists/reorder", json={"ids": order}, headers=h)
    assert [w["id"] for w in r.json()] == order
    assert [w["position"] for w in r.json()] == [0, 1, 2]
    # Every id once, no more, no less.
    assert (
        client.post("/v1/watchlists/reorder", json={"ids": order[:2]}, headers=h).status_code == 422
    )
    assert (
        client.post("/v1/watchlists/reorder", json={"ids": [*order, 999]}, headers=h).status_code
        == 422
    )

    assert client.delete(f"/v1/watchlists/{earnings['id']}", headers=h).status_code == 204
    assert [w["id"] for w in client.get("/v1/watchlists", headers=h).json()] == order[:2]


def test_make_default_and_delete_default(session: Session, client: TestClient) -> None:
    _symbols(session, "AAPL")
    h = _headers(_user(session))
    default = _default(client, h)
    other = client.post("/v1/watchlists", json={"name": "Other"}, headers=h).json()
    r = client.patch(f"/v1/watchlists/{other['id']}", json={"is_default": True}, headers=h)
    assert r.json()["is_default"] is True
    lists = client.get("/v1/watchlists", headers=h).json()
    assert [w["is_default"] for w in lists] == [False, True]
    assert (
        client.patch(
            f"/v1/watchlists/{other['id']}", json={"is_default": False}, headers=h
        ).status_code
        == 422
    )

    # The old routes follow the default.
    client.post("/v1/watchlist/AAPL", headers=h)
    items = client.get(f"/v1/watchlists/{other['id']}/items", headers=h).json()["items"]
    assert [i["ticker"] for i in items] == ["AAPL"]

    # Deleting the default moves the flag to the first remaining list.
    client.delete(f"/v1/watchlists/{other['id']}", headers=h)
    lists = client.get("/v1/watchlists", headers=h).json()
    assert [(w["id"], w["is_default"]) for w in lists] == [(default["id"], True)]

    # Deleting the last list leaves an empty Default.
    assert client.delete(f"/v1/watchlists/{default['id']}", headers=h).status_code == 204
    lists = client.get("/v1/watchlists", headers=h).json()
    assert len(lists) == 1 and lists[0]["name"] == "Default" and lists[0]["is_default"]
    assert lists[0]["item_count"] == 0
    assert client.get("/v1/watchlist", headers=h).json() == []


def test_lists_are_per_user(session: Session, client: TestClient) -> None:
    _symbols(session, "AAPL")
    alice, bob = _headers(_user(session, "a@x.dev")), _headers(_user(session, "b@x.dev"))
    mine = client.post("/v1/watchlists", json={"name": "Mine"}, headers=alice).json()
    # Bob may reuse the name, and cannot see, change or fill Alice's list.
    assert client.post("/v1/watchlists", json={"name": "Mine"}, headers=bob).status_code == 201
    wid = mine["id"]
    assert client.get(f"/v1/watchlists/{wid}/items", headers=bob).status_code == 404
    assert (
        client.patch(f"/v1/watchlists/{wid}", json={"name": "Taken"}, headers=bob).status_code
        == 404
    )
    assert (
        client.post(
            f"/v1/watchlists/{wid}/items", json={"tickers": ["AAPL"]}, headers=bob
        ).status_code
        == 404
    )
    assert client.delete(f"/v1/watchlists/{wid}", headers=bob).status_code == 404
    assert (
        client.post("/v1/watchlists/reorder", json={"ids": [wid]}, headers=bob).status_code == 422
    )
    assert {w["name"] for w in client.get("/v1/watchlists", headers=bob).json()} == {
        "Default",
        "Mine",
    }
    # Column sets too.
    cs = client.post(
        "/v1/column-sets", json={"name": "Mine", "columns": ["pe"]}, headers=alice
    ).json()
    assert (
        client.patch(f"/v1/column-sets/{cs['id']}", json={"name": "Z"}, headers=bob).status_code
        == 404
    )
    assert client.delete(f"/v1/column-sets/{cs['id']}", headers=bob).status_code == 404
    bobs = _default(client, bob)
    assert (
        client.patch(
            f"/v1/watchlists/{bobs['id']}", json={"column_set_id": cs["id"]}, headers=bob
        ).status_code
        == 404
    )
    assert (
        client.get(
            f"/v1/watchlists/{bobs['id']}/items?column_set_id={cs['id']}", headers=bob
        ).status_code
        == 404
    )


def test_bulk_add_dedupes_and_reports(session: Session, client: TestClient) -> None:
    _symbols(session, "AAPL", "MSFT", "NVDA")
    h = _headers(_user(session))
    wid = _default(client, h)["id"]
    client.post("/v1/watchlist/AAPL", headers=h)
    r = client.post(
        f"/v1/watchlists/{wid}/items",
        json={"tickers": ["msft", "MSFT", " aapl ", "NOPE", "nvda", ""]},
        headers=h,
    )
    assert r.status_code == 200
    assert r.json() == {
        "added": ["MSFT", "NVDA"], "already_listed": ["AAPL"], "unknown": ["NOPE"], "item_count": 3,
    }  # fmt: skip
    # A rerun adds nothing.
    again = client.post(f"/v1/watchlists/{wid}/items", json={"tickers": ["MSFT"]}, headers=h).json()
    assert again["added"] == [] and again["item_count"] == 3
    lists = client.get("/v1/watchlists?contains=msft", headers=h).json()
    assert lists[0]["item_count"] == 3 and lists[0]["contains"] is True
    assert (
        client.post(f"/v1/watchlists/{wid}/items", json={"tickers": []}, headers=h).status_code
        == 422
    )
    assert (
        client.post(f"/v1/watchlists/{wid}/items", json={"tickers": [" "]}, headers=h).status_code
        == 422
    )


def test_bulk_add_limits(session: Session, client: TestClient, monkeypatch) -> None:
    tickers = [f"T{i:03d}" for i in range(101)]
    for t in tickers:
        session.add(Symbol(ticker=t, name=t))
    session.commit()
    h = _headers(_user(session))
    wid = _default(client, h)["id"]
    # More than 100 in one request is refused by the schema.
    assert (
        client.post(f"/v1/watchlists/{wid}/items", json={"tickers": tickers}, headers=h).status_code
        == 422
    )
    # A list holds at most MAX_ITEMS; past it nothing is added.
    monkeypatch.setattr(svc, "MAX_ITEMS", 5)
    assert (
        client.post(
            f"/v1/watchlists/{wid}/items", json={"tickers": tickers[:4]}, headers=h
        ).status_code
        == 200
    )
    r = client.post(f"/v1/watchlists/{wid}/items", json={"tickers": tickers[4:6]}, headers=h)
    assert r.status_code == 409
    assert len(client.get(f"/v1/watchlists/{wid}/items", headers=h).json()["items"]) == 4
    monkeypatch.setattr(svc, "MAX_LISTS", 2)
    assert client.post("/v1/watchlists", json={"name": "Two"}, headers=h).status_code == 201
    assert client.post("/v1/watchlists", json={"name": "Three"}, headers=h).status_code == 409


def test_notes_and_tags(session: Session, client: TestClient) -> None:
    _symbols(session, "AAPL")
    h = _headers(_user(session))
    wid = _default(client, h)["id"]
    client.post(f"/v1/watchlists/{wid}/items", json={"tickers": ["AAPL"]}, headers=h)
    url = f"/v1/watchlists/{wid}/items/aapl"
    r = client.patch(
        url,
        json={"note": "  Base breakout above 200  ", "tags": ["Stage 2", "stage  2", "earnings"]},
        headers=h,
    )
    assert r.status_code == 200
    assert (r.json()["note"], r.json()["tags"]) == (
        "Base breakout above 200",
        ["Stage 2", "earnings"],
    )
    # Only the fields sent change.
    r = client.patch(url, json={"tags": ["F&O liquid"]}, headers=h)
    assert (r.json()["note"], r.json()["tags"]) == ("Base breakout above 200", ["F&O liquid"])
    row = client.get(f"/v1/watchlists/{wid}/items", headers=h).json()["items"][0]
    assert (row["note"], row["tags"]) == ("Base breakout above 200", ["F&O liquid"])
    # Blank clears the note.
    assert client.patch(url, json={"note": "   "}, headers=h).json()["note"] is None
    # Validation.
    assert client.patch(url, json={"note": "x" * 2001}, headers=h).status_code == 422
    assert (
        client.patch(url, json={"tags": [f"t{i}" for i in range(11)]}, headers=h).status_code == 422
    )
    assert client.patch(url, json={"tags": ["x" * 25]}, headers=h).status_code == 422
    assert client.patch(url, json={"tags": ["a,b"]}, headers=h).status_code == 422
    assert (
        client.patch(f"/v1/watchlists/{wid}/items/MSFT", json={"note": "x"}, headers=h).status_code
        == 404
    )


def test_column_sets_crud_and_allow_list(session: Session, client: TestClient) -> None:
    h = _headers(_user(session))
    r = client.post(
        "/v1/column-sets",
        json={"name": "Momentum", "columns": ["close", "rsi_14", "volume_ratio"]},
        headers=h,
    )
    assert r.status_code == 201
    cs = r.json()
    assert cs["columns"] == ["close", "rsi_14", "volume_ratio"]
    assert (
        client.post(
            "/v1/column-sets", json={"name": "Bad", "columns": ["password_hash"]}, headers=h
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/v1/column-sets", json={"name": "Dup", "columns": ["pe", "pe"]}, headers=h
        ).status_code
        == 422
    )
    assert (
        client.post("/v1/column-sets", json={"name": "Empty", "columns": []}, headers=h).status_code
        == 422
    )
    assert (
        client.post(
            "/v1/column-sets", json={"name": "momentum", "columns": ["pe"]}, headers=h
        ).status_code
        == 409
    )
    r = client.patch(f"/v1/column-sets/{cs['id']}", json={"columns": ["pe", "close"]}, headers=h)
    assert r.json()["columns"] == ["pe", "close"] and r.json()["name"] == "Momentum"
    assert [s["id"] for s in client.get("/v1/column-sets", headers=h).json()] == [cs["id"]]

    # A list remembers a set; deleting the set clears it.
    wid = _default(client, h)["id"]
    assert (
        client.patch(f"/v1/watchlists/{wid}", json={"column_set_id": cs["id"]}, headers=h).json()[
            "column_set_id"
        ]
        == cs["id"]
    )
    body = client.get(f"/v1/watchlists/{wid}/items", headers=h).json()
    assert (body["columns"], body["column_set_id"]) == (["pe", "close"], cs["id"])
    assert client.delete(f"/v1/column-sets/{cs['id']}", headers=h).status_code == 204
    assert _default(client, h)["column_set_id"] is None
    body = client.get(f"/v1/watchlists/{wid}/items", headers=h).json()
    assert body["columns"] == list(svc.DEFAULT_COLUMNS) and body["column_set_id"] is None
    # columns= overrides, and is checked against the allow-list too.
    body = client.get(f"/v1/watchlists/{wid}/items?columns=pe,sector", headers=h).json()
    assert body["columns"] == ["pe", "sector"]
    assert client.get(f"/v1/watchlists/{wid}/items?columns=pe,nope", headers=h).status_code == 422


def test_column_values_batched_with_missing_data(session: Session, client: TestClient) -> None:
    _symbols(session, "AAPL", "MSFT", bars=3)
    session.add(Symbol(ticker="RELIANCE.NS", name="Reliance", currency="INR"))  # no bars, no data
    session.commit()
    ids = instrument_ids(session, ["AAPL", "RELIANCE.NS"])
    session.add(
        SymbolMetrics(
            ticker="AAPL", as_of=date(2026, 11, 4), last_close=Decimal("102"), rsi_14=61.5,
            high_52w=Decimal("120"), low_52w=Decimal("80"), sma_50=100.0, sma_200=85.0,
            atr_pct_14=2.5, hv_20=22.0, avg_volume_20=1500.0, pe=30.0, market_cap_usd=3e12,
        )
    )  # fmt: skip
    session.add(
        ChecklistScore(
            instrument_id=ids["AAPL"],
            session_date=date(2026, 11, 3),
            met_count=2,
            evaluated_count=6,
        )
    )
    session.add(
        ChecklistScore(
            instrument_id=ids["AAPL"],
            session_date=date(2026, 11, 4),
            met_count=4,
            evaluated_count=5,
        )
    )
    session.add(DataFile(id=1, source="nse_sec_full", file_name="x.csv", sha256="0" * 64,
                         size_bytes=1, archived_path="x", parse_status="parsed"))  # fmt: skip
    session.flush()
    session.add(
        EodExtras(
            instrument_id=ids["RELIANCE.NS"],
            session_date=date(2026, 11, 3),
            series="EQ",
            delivery_pct=Decimal("40"),
            data_file_id=1,
        )
    )
    session.add(
        EodExtras(
            instrument_id=ids["RELIANCE.NS"],
            session_date=date(2026, 11, 4),
            series="BE",
            delivery_pct=Decimal("10"),
            data_file_id=1,
        )
    )
    session.add(
        EodExtras(
            instrument_id=ids["RELIANCE.NS"],
            session_date=date(2026, 11, 4),
            series="EQ",
            delivery_pct=Decimal("61.5"),
            data_file_id=1,
        )
    )
    session.commit()

    h = _headers(_user(session))
    wid = _default(client, h)["id"]
    client.post(
        f"/v1/watchlists/{wid}/items", json={"tickers": ["AAPL", "MSFT", "RELIANCE.NS"]}, headers=h
    )
    columns = ",".join(svc.COLUMN_KEYS)

    statements: list[str] = []
    bind = session.get_bind()

    def count(_conn, _cursor, statement, *_args):
        statements.append(statement)

    event.listen(bind, "before_cursor_execute", count)
    try:
        body = client.get(f"/v1/watchlists/{wid}/items?columns={columns}", headers=h).json()
    finally:
        event.remove(bind, "before_cursor_execute", count)
    # A fixed number of queries, whatever the row count: bars once, metrics,
    # latest volume, delivery and checklist once each.
    assert sum("price_bars" in s for s in statements) == 2
    assert len(statements) <= 12

    rows = {r["ticker"]: r["values"] for r in body["items"]}
    aapl = rows["AAPL"]
    assert aapl["close"] == 102.0
    assert aapl["change_pct"] == pytest.approx((102 / 101 - 1) * 100)
    assert aapl["rsi_14"] == 61.5
    assert aapl["pct_from_52w_high"] == pytest.approx((102 / 120 - 1) * 100)
    assert aapl["sma_50_gap_pct"] == pytest.approx(2.0)
    assert aapl["sma_200_gap_pct"] == pytest.approx((102 / 85 - 1) * 100)
    assert aapl["volume_ratio"] == pytest.approx(3000 / 1500)
    assert aapl["pe"] == 30.0 and aapl["pb"] is None and aapl["market_cap_usd"] == 3e12
    assert (aapl["checklist_met"], aapl["checklist_evaluated"]) == (4, 5)
    assert aapl["delivery_pct"] is None
    assert aapl["sector"] == "Technology"
    # No metrics row: every metric is null, never 0; closes still count.
    msft = rows["MSFT"]
    assert msft["close"] == 102.0 and msft["rsi_14"] is None and msft["volume_ratio"] is None
    assert msft["checklist_met"] is None and msft["sector"] is None
    # No bars at all; delivery from the newest session, EQ over BE.
    rel = rows["RELIANCE.NS"]
    assert rel["close"] is None and rel["change_pct"] is None
    assert rel["delivery_pct"] == 61.5
    assert body["watchlist"]["item_count"] == 3


def test_old_routes_still_work_against_default(session: Session, client: TestClient) -> None:
    _symbols(session, "AAPL", "MSFT")
    h = _headers(_user(session))
    assert client.post("/v1/watchlist/AAPL", headers=h).status_code == 201
    # A new non-default list does not change what the old routes see.
    other = client.post("/v1/watchlists", json={"name": "Other"}, headers=h).json()
    client.post(f"/v1/watchlists/{other['id']}/items", json={"tickers": ["MSFT"]}, headers=h)
    assert [r["ticker"] for r in client.get("/v1/watchlist", headers=h).json()] == ["AAPL"]
    assert client.delete("/v1/watchlist/MSFT", headers=h).status_code == 404
    # Per-list removal.
    assert client.delete(f"/v1/watchlists/{other['id']}/items/msft", headers=h).status_code == 204
    assert client.delete(f"/v1/watchlists/{other['id']}/items/msft", headers=h).status_code == 404
    lists = client.get("/v1/watchlists?contains=AAPL", headers=h).json()
    assert [(w["name"], w["contains"]) for w in lists] == [("Default", True), ("Other", False)]


def test_an_existing_list_becomes_the_default(session: Session, client: TestClient) -> None:
    """A user with lists but no flagged default (rows before A2.5's backfill)."""
    from stockviz.models import Watchlist

    user_id = _user(session)
    session.add(Watchlist(user_id=user_id, name="Old", position=0))
    session.commit()
    lists = client.get("/v1/watchlists", headers=_headers(user_id)).json()
    assert [(w["name"], w["is_default"]) for w in lists] == [("Old", True)]
