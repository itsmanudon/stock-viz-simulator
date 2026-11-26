"""A5.1 books (M10.1): CRUD, ``?book=`` on every book route, isolation.

Covers the design note's acceptance for books: an order in book B leaves
book A untouched; two concurrent first requests create one default (the
PostgreSQL test at the end); every book route takes ``?book=`` and answers
404 for another user's book; archived and imported books take no trades.
"""

from __future__ import annotations

import threading
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from jose import jwt as jose_jwt
from sqlmodel import Session, col, select

from stockviz.models import (
    MAX_BOOKS_PER_USER,
    Alert,
    AlertKind,
    CorporateAction,
    CorporateActionApplication,
    PendingOrder,
    Portfolio,
    PortfolioSnapshot,
    Position,
    PriceBar,
    Symbol,
    Trade,
    TradeSide,
    User,
)
from stockviz.services.corporate_actions.apply import apply_due_splits
from stockviz.services.trading import ensure_default_portfolio, execute_trade
from stockviz.services.trading.books import BookNotFound, BookNotWritable, resolve_book
from stockviz.services.trading.snapshots import snapshot_user_navs
from stockviz.settings import get_settings
from tests.pg_scratch import postgres_admin_url, scratch_postgres_engine

SECRET = get_settings().internal_api_token


def _h(user_id: int) -> dict[str, str]:
    token = jose_jwt.encode({"sub": str(user_id)}, SECRET, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


def _user(session: Session, email: str | None = None) -> int:
    user = User(email=email or f"{uuid4().hex}@stockviz.dev", name="Booker")
    session.add(user)
    session.commit()
    session.refresh(user)
    assert user.id is not None
    return user.id


def _market(session: Session, ticker: str = "AAPL", close: str = "150") -> None:
    if session.get(Symbol, ticker) is None:
        session.add(Symbol(ticker=ticker, name=ticker, currency="USD"))
        session.commit()
    price = Decimal(close)
    session.add(
        PriceBar(
            ticker=ticker,
            ts=datetime(2025, 4, 10),
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


def _create(client: TestClient, user_id: int, **body) -> dict:
    body.setdefault("name", f"Book {uuid4().hex[:6]}")
    response = client.post("/v1/books", json=body, headers=_h(user_id))
    assert response.status_code == 201, response.text
    return response.json()


# --- CRUD --------------------------------------------------------------------


def test_list_creates_the_default_book_first(session: Session, client: TestClient) -> None:
    uid = _user(session)
    body = client.get("/v1/books", headers=_h(uid)).json()
    assert body["limit"] == MAX_BOOKS_PER_USER == 20
    [book] = body["books"]
    assert book["is_default"] and book["kind"] == "paper" and book["writable"]
    assert book["cash_tracked"] and book["holder_kind"] == "self" and book["activity"] == []


def test_create_paper_books_start_with_their_currencys_cash(
    session: Session, client: TestClient
) -> None:
    uid = _user(session)
    usd = _create(client, uid, name="Swing")
    inr = _create(
        client, uid, name="India", base_currency="INR", holder_kind="family", holder_label="Mum"
    )
    assert not usd["is_default"] and usd["base_currency"] == "USD"
    assert inr["holder_label"] == "Mum" and inr["holder_kind"] == "family"
    for book, cash in ((usd, "100000"), (inr, "10000000")):
        row = session.get(Portfolio, book["id"])
        assert row is not None
        assert row.cash_balance == Decimal(cash) == row.opening_nav
        snap = session.exec(
            select(PortfolioSnapshot).where(PortfolioSnapshot.portfolio_id == book["id"])
        ).one()  # a day-zero snapshot, like the default book
        assert snap.nav == Decimal(cash)
    portfolio = client.get(f"/v1/portfolio?book={inr['id']}", headers=_h(uid)).json()
    assert portfolio["base_currency"] == "INR"


def test_an_imported_book_is_holdings_only_and_takes_no_trades(
    session: Session, client: TestClient
) -> None:
    _market(session)
    uid = _user(session)
    book = _create(client, uid, name="Zerodha", kind="imported")
    assert book["broker"] == "zerodha" and not book["cash_tracked"] and not book["writable"]
    row = session.get(Portfolio, book["id"])
    assert row is not None and row.cash_balance == 0
    trade = client.post(
        f"/v1/trades?book={book['id']}",
        json={"ticker": "AAPL", "side": "buy", "quantity": "1"},
        headers=_h(uid),
    )
    assert trade.status_code == 409 and "imported" in trade.json()["detail"]
    order = client.post(
        f"/v1/orders?book={book['id']}",
        json={
            "ticker": "AAPL",
            "side": "buy",
            "order_type": "limit",
            "quantity": "1",
            "limit_price": "100",
        },
        headers=_h(uid),
    )
    assert order.status_code == 409
    # Every read route still answers for it.
    for path in (
        "/v1/portfolio",
        "/v1/portfolio/overview",
        "/v1/portfolio/analytics",
        "/v1/trades",
        "/v1/orders",
        "/v1/portfolio/history",
    ):
        assert client.get(f"{path}?book={book['id']}", headers=_h(uid)).status_code == 200, path


def test_names_are_unique_ignoring_case_and_labels_never_hold_a_pan(
    session: Session, client: TestClient
) -> None:
    uid = _user(session)
    _create(client, uid, name="Swing")
    dup = client.post("/v1/books", json={"name": "  swing "}, headers=_h(uid))
    assert dup.status_code == 409
    pan = client.post(
        "/v1/books",
        json={"name": "HUF", "holder_kind": "huf", "holder_label": "ABCDE1234F"},
        headers=_h(uid),
    )
    assert pan.status_code == 422 and "PAN" in pan.json()["detail"]
    other = _user(session)
    assert client.post("/v1/books", json={"name": "Swing"}, headers=_h(other)).status_code == 201


def test_the_cap_is_twenty_books(session: Session, client: TestClient) -> None:
    uid = _user(session)
    client.get("/v1/books", headers=_h(uid))  # the default is book 1
    for n in range(MAX_BOOKS_PER_USER - 1):
        _create(client, uid, name=f"B{n}")
    over = client.post("/v1/books", json={"name": "One more"}, headers=_h(uid))
    assert over.status_code == 409 and "20" in over.json()["detail"]


def test_patch_renames_relabels_archives_and_moves_the_default(
    session: Session, client: TestClient
) -> None:
    uid = _user(session)
    default = client.get("/v1/books", headers=_h(uid)).json()["books"][0]
    other = _create(client, uid, name="Other", holder_label="Dad")

    renamed = client.patch(
        f"/v1/books/{other['id']}",
        json={"name": "Long term", "holder_label": None},
        headers=_h(uid),
    ).json()
    assert renamed["name"] == "Long term" and renamed["holder_label"] is None

    # The default can't be archived; moving the default first makes it possible.
    refused = client.patch(f"/v1/books/{default['id']}", json={"archived": True}, headers=_h(uid))
    assert refused.status_code == 409
    moved = client.patch(f"/v1/books/{other['id']}", json={"is_default": True}, headers=_h(uid))
    assert moved.json()["is_default"]
    books = {b["id"]: b for b in client.get("/v1/books", headers=_h(uid)).json()["books"]}
    assert not books[default["id"]]["is_default"]
    assert [b["id"] for b in books.values() if b["is_default"]] == [other["id"]]

    archived = client.patch(
        f"/v1/books/{default['id']}", json={"archived": True}, headers=_h(uid)
    ).json()
    assert archived["archived_at"] is not None and not archived["writable"]
    # An archived book can't become the default; unarchive restores it.
    again = client.patch(f"/v1/books/{default['id']}", json={"is_default": True}, headers=_h(uid))
    assert again.status_code == 409
    back = client.patch(f"/v1/books/{default['id']}", json={"archived": False}, headers=_h(uid))
    assert back.json()["archived_at"] is None


def test_an_imported_book_cannot_be_the_default(session: Session, client: TestClient) -> None:
    uid = _user(session)
    imported = _create(client, uid, name="Zerodha", kind="imported")
    r = client.patch(f"/v1/books/{imported['id']}", json={"is_default": True}, headers=_h(uid))
    assert r.status_code == 409


def test_archive_waits_for_pending_orders(session: Session, client: TestClient) -> None:
    _market(session)
    uid = _user(session)
    client.get("/v1/books", headers=_h(uid))
    book = _create(client, uid, name="Orders")
    placed = client.post(
        f"/v1/orders?book={book['id']}",
        json={
            "ticker": "AAPL",
            "side": "buy",
            "order_type": "limit",
            "quantity": "1",
            "limit_price": "100",
        },
        headers=_h(uid),
    )
    assert placed.status_code == 201
    r = client.patch(f"/v1/books/{book['id']}", json={"archived": True}, headers=_h(uid))
    assert r.status_code == 409 and "pending" in r.json()["detail"]
    assert client.delete(f"/v1/orders/{placed.json()['id']}", headers=_h(uid)).status_code == 204
    r = client.patch(f"/v1/books/{book['id']}", json={"archived": True}, headers=_h(uid))
    assert r.status_code == 200


def test_archived_books_are_readable_not_tradable(session: Session, client: TestClient) -> None:
    _market(session)
    uid = _user(session)
    client.get("/v1/books", headers=_h(uid))
    book = _create(client, uid, name="Old")
    buy = client.post(
        f"/v1/trades?book={book['id']}",
        json={"ticker": "AAPL", "side": "buy", "quantity": "2"},
        headers=_h(uid),
    )
    assert buy.status_code == 201
    client.patch(f"/v1/books/{book['id']}", json={"archived": True}, headers=_h(uid))
    sell = client.post(
        f"/v1/trades?book={book['id']}",
        json={"ticker": "AAPL", "side": "sell", "quantity": "1"},
        headers=_h(uid),
    )
    assert sell.status_code == 409 and "archived" in sell.json()["detail"]
    reset = client.put(
        f"/v1/portfolio/base-currency?book={book['id']}",
        json={"base_currency": "INR"},
        headers=_h(uid),
    )
    assert reset.status_code == 409
    portfolio = client.get(f"/v1/portfolio?book={book['id']}", headers=_h(uid)).json()
    assert [p["ticker"] for p in portfolio["positions"]] == ["AAPL"]
    with pytest.raises(BookNotWritable):
        resolve_book(session, uid, book["id"], write=True)


def test_delete_rules(session: Session, client: TestClient) -> None:
    _market(session)
    uid = _user(session)
    default = client.get("/v1/books", headers=_h(uid)).json()["books"][0]
    # The default (and last) book is never deleted.
    assert client.delete(f"/v1/books/{default['id']}", headers=_h(uid)).status_code == 409

    empty = _create(client, uid, name="Empty")
    assert client.delete(f"/v1/books/{empty['id']}", headers=_h(uid)).status_code == 204
    assert session.get(Portfolio, empty["id"]) is None

    used = _create(client, uid, name="Used")
    client.post(
        f"/v1/trades?book={used['id']}",
        json={"ticker": "AAPL", "side": "buy", "quantity": "3"},
        headers=_h(uid),
    )
    client.post(
        "/v1/alerts",
        json={
            "kind": "portfolio",
            "params": {"metric": "drawdown_pct", "threshold": 10},
            "book_id": used["id"],
        },
        headers=_h(uid),
    )
    refused = client.delete(f"/v1/books/{used['id']}", headers=_h(uid))
    assert refused.status_code == 409 and "Archive" in refused.json()["detail"]
    client.patch(f"/v1/books/{used['id']}", json={"archived": True}, headers=_h(uid))
    assert client.delete(f"/v1/books/{used['id']}", headers=_h(uid)).status_code == 204
    session.expire_all()
    assert session.get(Portfolio, used["id"]) is None
    for model in (Trade, Position, PortfolioSnapshot):
        rows = session.exec(select(model).where(model.portfolio_id == used["id"])).all()  # type: ignore[attr-defined]
        assert rows == [], model
    assert session.exec(select(Alert).where(Alert.portfolio_id == used["id"])).all() == []
    # The default book is untouched.
    assert session.get(Portfolio, default["id"]) is not None


def test_another_users_book_is_404_everywhere(session: Session, client: TestClient) -> None:
    _market(session)
    owner = _user(session)
    stranger = _user(session)
    book = _create(client, owner, name="Mine")
    bid = book["id"]
    reads = [
        "/v1/portfolio",
        "/v1/portfolio/overview",
        "/v1/portfolio/analytics",
        "/v1/portfolio/risk",
        "/v1/portfolio/stress",
        "/v1/portfolio/limits",
        "/v1/portfolio/limits/check?ticker=AAPL&quantity=1",
        "/v1/portfolio/history",
        "/v1/portfolio/dividends",
        "/v1/trades",
        "/v1/orders",
        "/v1/options/positions",
        "/v1/options/strategies",
        "/v1/options/book",
        "/v1/portfolio/journal/months/2026/8",
        "/v1/portfolio/journal/days/2026-08-03",
        "/v1/portfolio/journal/weeks/2026-08-03",
        "/v1/earnings?scope=holdings",
        "/v1/symbols/AAPL/events",
    ]
    for path in reads:
        sep = "&" if "?" in path else "?"
        url = f"{path}{sep}book={bid}"
        assert client.get(url, headers=_h(stranger)).status_code == 404, url
        assert client.get(url, headers=_h(owner)).status_code == 200, url
    writes = [
        ("post", "/v1/trades", {"ticker": "AAPL", "side": "buy", "quantity": "1"}),
        (
            "post",
            "/v1/orders",
            {
                "ticker": "AAPL",
                "side": "buy",
                "order_type": "limit",
                "quantity": "1",
                "limit_price": "100",
            },
        ),
        ("put", "/v1/portfolio/base-currency", {"base_currency": "INR"}),
        ("put", "/v1/portfolio/limits", {}),
    ]
    for method, path, body in writes:
        r = getattr(client, method)(f"{path}?book={bid}", json=body, headers=_h(stranger))
        assert r.status_code == 404, path
    for method, body in (("patch", {"name": "x"}), ("delete", None)):
        kwargs = {"json": body} if body is not None else {}
        r = getattr(client, method)(f"/v1/books/{bid}", headers=_h(stranger), **kwargs)
        assert r.status_code == 404, method
    alert = client.post(
        "/v1/alerts",
        json={
            "kind": "portfolio",
            "params": {"metric": "drawdown_pct", "threshold": 10},
            "book_id": bid,
        },
        headers=_h(stranger),
    )
    assert alert.status_code == 404
    with pytest.raises(BookNotFound):
        resolve_book(session, stranger, bid)
    assert client.get("/v1/portfolio?book=999999", headers=_h(owner)).status_code == 404


# --- isolation ---------------------------------------------------------------


def test_a_trade_and_an_order_in_book_b_leave_book_a_untouched(
    session: Session, client: TestClient
) -> None:
    _market(session)
    uid = _user(session)
    a = client.get("/v1/portfolio", headers=_h(uid)).json()
    b = _create(client, uid, name="B")
    buy = client.post(
        f"/v1/trades?book={b['id']}",
        json={"ticker": "AAPL", "side": "buy", "quantity": "10"},
        headers=_h(uid),
    )
    assert buy.status_code == 201
    order = client.post(
        f"/v1/orders?book={b['id']}",
        json={
            "ticker": "AAPL",
            "side": "sell",
            "order_type": "limit",
            "quantity": "5",
            "limit_price": "200",
        },
        headers=_h(uid),
    )
    assert order.status_code == 201

    after_a = client.get("/v1/portfolio", headers=_h(uid)).json()
    assert after_a["cash_balance"] == a["cash_balance"] and after_a["positions"] == []
    assert client.get("/v1/trades", headers=_h(uid)).json() == []
    assert client.get("/v1/orders", headers=_h(uid)).json() == []

    in_b = client.get(f"/v1/portfolio?book={b['id']}", headers=_h(uid)).json()
    assert [p["ticker"] for p in in_b["positions"]] == ["AAPL"]
    assert Decimal(in_b["cash_balance"]) == Decimal("100000") - Decimal("1500")
    assert len(client.get(f"/v1/trades?book={b['id']}", headers=_h(uid)).json()) == 1
    assert len(client.get(f"/v1/orders?book={b['id']}", headers=_h(uid)).json()) == 1
    # Selling in A what only B holds is refused.
    sell_a = client.post(
        "/v1/trades", json={"ticker": "AAPL", "side": "sell", "quantity": "1"}, headers=_h(uid)
    )
    assert sell_a.status_code == 422


def test_cancel_finds_the_orders_own_book(session: Session, client: TestClient) -> None:
    _market(session)
    uid = _user(session)
    client.get("/v1/books", headers=_h(uid))
    b = _create(client, uid, name="B")
    order = client.post(
        f"/v1/orders?book={b['id']}",
        json={
            "ticker": "AAPL",
            "side": "buy",
            "order_type": "limit",
            "quantity": "1",
            "limit_price": "100",
        },
        headers=_h(uid),
    ).json()
    stranger = _user(session)
    assert client.delete(f"/v1/orders/{order['id']}", headers=_h(stranger)).status_code == 404
    assert client.delete(f"/v1/orders/{order['id']}", headers=_h(uid)).status_code == 204
    row = session.get(PendingOrder, order["id"])
    assert row is not None and row.status == "cancelled"


def test_nightly_snapshots_are_one_row_per_book(session: Session, client: TestClient) -> None:
    _market(session)
    uid = _user(session)
    a = ensure_default_portfolio(session, uid)
    b = _create(client, uid, name="B")
    execute_trade(
        session,
        user_id=uid,
        ticker="AAPL",
        side=TradeSide.BUY,
        quantity=Decimal(10),
        book_id=b["id"],
    )
    written = snapshot_user_navs(session, snapshot_date=date(2025, 4, 10))
    assert written == 2
    rows = session.exec(
        select(PortfolioSnapshot).where(PortfolioSnapshot.date == date(2025, 4, 10))
    ).all()
    assert {r.portfolio_id for r in rows} == {a.id, b["id"]}
    assert {r.user_id for r in rows} == {uid}
    history_a = client.get("/v1/portfolio/history?days=3650", headers=_h(uid)).json()
    history_b = client.get(
        f"/v1/portfolio/history?days=3650&book={b['id']}", headers=_h(uid)
    ).json()
    assert {h["date"] for h in history_a} & {h["date"] for h in history_b}
    assert len(history_a) == len(history_b) == 2  # day zero + the nightly row, each book


def test_split_rebases_each_book_once(session: Session) -> None:
    session.add(Symbol(ticker="AAPL", name="Apple", currency="USD"))
    session.commit()
    uid = _user(session)
    a = ensure_default_portfolio(session, uid)
    b = Portfolio(user_id=uid, name="B", is_default=False, cash_balance=Decimal(1000))
    session.add(b)
    session.commit()
    session.refresh(b)
    before = datetime(2026, 8, 20, 15)
    for book in (a, b):
        assert book.id is not None
        session.add(
            Trade(
                portfolio_id=book.id,
                ticker="AAPL",
                side=TradeSide.BUY,
                quantity=Decimal(10),
                price=Decimal(200),
                ts=before,
            )
        )
        session.add(
            Position(
                portfolio_id=book.id, ticker="AAPL", quantity=Decimal(10), avg_cost=Decimal(200)
            )
        )
    session.add(
        CorporateAction(
            ticker="AAPL",
            kind="split",
            ex_date=date(2026, 8, 31),
            ratio_from=Decimal(1),
            ratio_to=Decimal(4),
            source="test",
        )
    )
    session.commit()
    now = datetime(2026, 9, 1, 2, tzinfo=UTC)

    assert apply_due_splits(session, now=now).users_rebased == 1
    positions = session.exec(select(Position).order_by(col(Position.portfolio_id))).all()
    assert [(p.quantity, p.avg_cost) for p in positions] == [(Decimal(40), Decimal(50))] * 2
    rows = session.exec(select(CorporateActionApplication)).all()
    assert sorted((r.portfolio_id or 0) for r in rows) == sorted([0, a.id or 0, b.id or 0])

    assert apply_due_splits(session, now=now).users_rebased == 0
    again = session.exec(select(Position).order_by(col(Position.portfolio_id))).all()
    assert [p.quantity for p in again] == [Decimal(40)] * 2


def test_portfolio_alerts_watch_their_own_book(session: Session, client: TestClient) -> None:
    uid = _user(session)
    client.get("/v1/books", headers=_h(uid))
    b = _create(client, uid, name="B")
    r = client.post(
        "/v1/alerts",
        json={
            "kind": "portfolio",
            "params": {"metric": "drawdown_pct", "threshold": 10},
            "book_id": b["id"],
        },
        headers=_h(uid),
    )
    assert r.status_code == 201 and r.json()["book_id"] == b["id"]
    row = session.get(Alert, r.json()["id"])
    assert row is not None and row.kind == AlertKind.PORTFOLIO and row.portfolio_id == b["id"]
    price = client.post(
        "/v1/alerts",
        json={"ticker": "AAPL", "direction": "above", "target_price": "1", "book_id": b["id"]},
        headers=_h(uid),
    )
    assert price.status_code in (400, 404)


def test_fill_events_carry_their_book(session: Session, client: TestClient) -> None:
    _market(session)
    uid = _user(session)
    client.get("/v1/books", headers=_h(uid))
    b = _create(client, uid, name="B")
    client.post(
        f"/v1/trades?book={b['id']}",
        json={"ticker": "AAPL", "side": "buy", "quantity": "1"},
        headers=_h(uid),
    )
    url = "/v1/symbols/AAPL/events?types=fill&from=2025-01-01"
    fills = client.get(url, headers=_h(uid)).json()["events"]
    assert [f["book_id"] for f in fills] == [b["id"]]
    default = client.get("/v1/books", headers=_h(uid)).json()["books"][0]["id"]
    only_default = client.get(f"{url}&book={default}", headers=_h(uid)).json()["events"]
    assert only_default == []


# --- PostgreSQL: the default-book race ---------------------------------------


@pytest.mark.skipif(postgres_admin_url() is None, reason="DATABASE_URL is not PostgreSQL")
def test_two_concurrent_first_requests_create_one_default_book() -> None:
    with scratch_postgres_engine() as engine:
        with Session(engine) as setup:
            uid = _user(setup)
        barrier = threading.Barrier(4)
        ids: list[int] = []
        errors: list[BaseException] = []

        def first_request() -> None:
            try:
                with Session(engine) as s:
                    barrier.wait()
                    book = ensure_default_portfolio(s, uid)
                    assert book.id is not None
                    ids.append(book.id)
            except BaseException as exc:  # pragma: no cover - reported below
                errors.append(exc)

        threads = [threading.Thread(target=first_request) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors, errors
        assert len(set(ids)) == 1
        with Session(engine) as check:
            books = check.exec(select(Portfolio).where(Portfolio.user_id == uid)).all()
            assert len(books) == 1 and books[0].is_default
            # The partial unique index refuses a second default outright.
            check.add(
                Portfolio(user_id=uid, name="Second", is_default=True, cash_balance=Decimal(1))
            )
            with pytest.raises(Exception, match="uq_portfolios_user_default"):
                check.commit()


def test_risk_limits_are_per_book(session: Session, client: TestClient) -> None:
    uid = _user(session)
    client.get("/v1/books", headers=_h(uid))
    b = _create(client, uid, name="Capped")
    r = client.put(
        f"/v1/portfolio/limits?book={b['id']}", json={"max_position_pct": "10"}, headers=_h(uid)
    )
    assert r.status_code == 200 and Decimal(r.json()["max_position_pct"]) == 10
    assert client.get("/v1/portfolio/limits", headers=_h(uid)).json()["max_position_pct"] is None
    got = client.get(f"/v1/portfolio/limits?book={b['id']}", headers=_h(uid)).json()
    assert Decimal(got["max_position_pct"]) == 10
