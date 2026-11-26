"""A5.4 (M10.3): trade plans, the first-fill lock and plans on orders.

Covers the design note's plan acceptance: a plan written before the order
locks at its first fill (``locked_at`` = the fill's time) and refuses an edit
to its stop with 409 while notes and tags stay editable; a plan written for
a position that was already open is labelled "written after entry" and never
locked; plans are private to their user and belong to one book. The drill
and replay paths are in ``test_drills.py`` / ``test_replay*.py`` and the
migration with identical drill scores in ``test_trade_plans_migration.py``.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from fastapi.testclient import TestClient
from jose import jwt as jose_jwt
from sqlmodel import Session, select

from stockviz.models import PriceBar, Symbol, Trade, TradePlan, User
from stockviz.services.plans import record_fill
from stockviz.services.trading.orders import settle_pending_orders
from stockviz.settings import get_settings

SECRET = get_settings().internal_api_token
DAY = datetime(2025, 4, 10)
PLAN = {
    "planned_entry": "150",
    "planned_stop": "140",
    "planned_target": "175",
    "planned_size": "10",
}


def _h(user_id: int) -> dict[str, str]:
    token = jose_jwt.encode({"sub": str(user_id)}, SECRET, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


def _user(session: Session) -> int:
    user = User(email=f"{uuid4().hex}@stockviz.dev", name="Planner")
    session.add(user)
    session.commit()
    assert user.id is not None
    return user.id


def _bar(session: Session, ticker: str, ts: datetime, close: str) -> None:
    price = Decimal(close)
    session.add(
        PriceBar(
            ticker=ticker, ts=ts, interval="1d", open=price, high=price, low=price,
            close=price, volume=1_000_000, source="test",
        )
    )  # fmt: skip
    session.commit()


def _market(session: Session, ticker: str = "AAPL", close: str = "150") -> None:
    if session.get(Symbol, ticker) is None:
        session.add(Symbol(ticker=ticker, name=ticker, currency="USD"))
        session.commit()
    _bar(session, ticker, DAY, close)


def _plan(client: TestClient, uid: int, ticker: str = "AAPL", book: int | None = None, **extra):
    q = f"?book={book}" if book else ""
    return client.post(f"/v1/plans{q}", json={"ticker": ticker, **PLAN, **extra}, headers=_h(uid))


def test_plan_locks_at_its_first_fill_and_refuses_edits_after(
    session: Session, client: TestClient
) -> None:
    _market(session)
    uid = _user(session)
    made = _plan(client, uid, tags=["breakout", " Breakout ", "base"], why="Tight base")
    assert made.status_code == 201, made.text
    plan = made.json()
    assert plan["status"] == "open" and not plan["locked"] and not plan["frozen"]
    assert plan["tags"] == ["breakout", "base"]  # de-duplicated ignoring case
    assert plan["risk_per_share"] == "10.000000" and plan["planned_risk"] == "100.000000"
    assert plan["reward_risk"] == "2.50"
    # Before a fill the plan can change.
    edit = client.patch(f"/v1/plans/{plan['id']}", json={"planned_stop": "141"}, headers=_h(uid))
    assert edit.status_code == 200 and edit.json()["planned_stop"] == "141.000000"

    trade = client.post(
        "/v1/trades",
        json={"ticker": "AAPL", "side": "buy", "quantity": "10", "trade_plan_id": plan["id"]},
        headers=_h(uid),
    )
    assert trade.status_code == 201, trade.text
    assert trade.json()["trade_plan_id"] == plan["id"]
    row = session.exec(select(Trade)).one()
    after = client.get(f"/v1/plans/{plan['id']}", headers=_h(uid)).json()
    assert after["status"] == "active" and after["locked"] and after["frozen"]
    assert not after["written_after_entry"] and after["fills"] == 1
    assert datetime.fromisoformat(after["locked_at"]) == row.ts
    assert after["first_fill_at"] == after["locked_at"]

    # The lock: plan fields 409, notes and tags 200.
    refused = client.patch(f"/v1/plans/{plan['id']}", json={"planned_stop": "130"}, headers=_h(uid))
    assert refused.status_code == 409 and "locked" in refused.json()["detail"]
    same = client.patch(f"/v1/plans/{plan['id']}", json={"planned_stop": "141"}, headers=_h(uid))
    assert same.status_code == 200  # sending the unchanged value is not an edit
    notes = client.patch(
        f"/v1/plans/{plan['id']}", json={"notes": "Held well", "tags": ["late"]}, headers=_h(uid)
    )
    assert notes.status_code == 200 and notes.json()["notes"] == "Held well"
    assert notes.json()["tags"] == ["late"]
    assert client.delete(f"/v1/plans/{plan['id']}", headers=_h(uid)).status_code == 409

    # Selling the whole position closes the plan.
    sold = client.post(
        "/v1/trades", json={"ticker": "AAPL", "side": "sell", "quantity": "10"}, headers=_h(uid)
    )
    assert sold.status_code == 201
    assert client.get(f"/v1/plans/{plan['id']}", headers=_h(uid)).json()["status"] == "closed"


def test_a_plan_written_on_the_ticket_is_created_with_the_order(
    session: Session, client: TestClient
) -> None:
    _market(session)
    uid = _user(session)
    res = client.post(
        "/v1/trades",
        json={
            "ticker": "AAPL",
            "side": "buy",
            "quantity": "4",
            "plan": {**PLAN, "planned_size": "4"},
        },
        headers=_h(uid),
    )
    assert res.status_code == 201, res.text
    plan_id = res.json()["trade_plan_id"]
    plan = client.get(f"/v1/plans/{plan_id}", headers=_h(uid)).json()
    assert plan["source"] == "paper" and plan["locked"] and plan["status"] == "active"
    # A refused order writes no plan (one transaction).
    bad = client.post(
        "/v1/trades",
        json={"ticker": "AAPL", "side": "buy", "quantity": "1000000", "plan": PLAN},
        headers=_h(uid),
    )
    assert bad.status_code == 422
    assert len(session.exec(select(TradePlan)).all()) == 1


def test_a_pending_order_links_its_fill_at_settlement(session: Session, client: TestClient) -> None:
    _market(session)
    uid = _user(session)
    res = client.post(
        "/v1/orders",
        json={"ticker": "AAPL", "side": "buy", "order_type": "limit", "quantity": "5",
              "limit_price": "149", "plan": {**PLAN, "planned_entry": "149"}},
        headers=_h(uid),
    )  # fmt: skip
    assert res.status_code == 201, res.text
    plan_id = res.json()["trade_plan_id"]
    assert client.get(f"/v1/plans/{plan_id}", headers=_h(uid)).json()["status"] == "open"
    _bar(session, "AAPL", datetime(2025, 4, 11), "148")
    assert settle_pending_orders(session, session_date=datetime(2025, 4, 11).date()) == 1
    trade = session.exec(select(Trade)).one()
    assert trade.trade_plan_id == plan_id
    plan = client.get(f"/v1/plans/{plan_id}", headers=_h(uid)).json()
    assert plan["locked"] and datetime.fromisoformat(plan["locked_at"]) == trade.ts


def test_a_plan_for_an_open_position_is_written_after_entry(
    session: Session, client: TestClient
) -> None:
    _market(session)
    uid = _user(session)
    for qty in ("3", "2"):
        res = client.post(
            "/v1/trades", json={"ticker": "AAPL", "side": "buy", "quantity": qty}, headers=_h(uid)
        )
        assert res.status_code == 201
    res = _plan(client, uid, link_open_position=True)
    assert res.status_code == 201, res.text
    plan = res.json()
    assert plan["written_after_entry"] and not plan["locked"] and plan["locked_at"] is None
    assert plan["frozen"] and plan["status"] == "active" and plan["fills"] == 2
    first = min(t.ts for t in session.exec(select(Trade)).all())
    assert datetime.fromisoformat(plan["first_fill_at"]) == first
    edit = client.patch(f"/v1/plans/{plan['id']}", json={"planned_stop": "139"}, headers=_h(uid))
    assert edit.status_code == 409 and "written after entry" in edit.json()["detail"]
    # The position has a plan now; a second one is refused.
    assert _plan(client, uid, link_open_position=True).status_code == 409
    # No position: nothing to link.
    _market(session, "MSFT", "300")
    none = _plan(client, uid, ticker="MSFT", link_open_position=True,
                 planned_entry="300", planned_stop="290", planned_target="330")  # fmt: skip
    assert none.status_code == 422


def test_record_fill_rule() -> None:
    plan = TradePlan(user_id=1, instrument_id=1, source="paper", portfolio_id=1,
                     created_at=datetime(2025, 1, 2))  # fmt: skip
    record_fill(plan, datetime(2025, 1, 3))
    assert plan.locked_at == datetime(2025, 1, 3) and not plan.written_after_entry
    record_fill(plan, datetime(2025, 1, 5))  # a later fill changes nothing
    assert plan.locked_at == datetime(2025, 1, 3)
    late = TradePlan(user_id=1, instrument_id=1, source="paper", portfolio_id=1,
                     created_at=datetime(2025, 1, 4))  # fmt: skip
    record_fill(late, datetime(2025, 1, 3))
    assert late.locked_at is None and late.written_after_entry and late.frozen
    replay = TradePlan(user_id=1, instrument_id=1, source="replay", replay_session_id=1,
                       created_at=datetime(2026, 11, 26))  # fmt: skip
    record_fill(replay, datetime(2020, 6, 1), plan_predates_fill=True)  # simulated time
    assert replay.locked_at == datetime(2020, 6, 1) and not replay.written_after_entry


def test_validation(session: Session, client: TestClient) -> None:
    _market(session)
    _market(session, "^GSPC", "5000")
    uid = _user(session)
    assert _plan(client, uid, planned_stop="155").status_code == 422  # stop above entry
    assert _plan(client, uid, planned_target="145").status_code == 422  # target below
    assert (
        _plan(client, uid, side="short", planned_stop="160", planned_target="120").status_code
        == 422
    )
    assert _plan(client, uid, ticker="NOPE").status_code == 404
    assert _plan(client, uid, ticker="^GSPC", planned_entry="5000",
                 planned_stop="4900", planned_target="5200").status_code == 422  # fmt: skip
    assert _plan(client, uid, setup_version_id=999).status_code == 404
    plan = _plan(client, uid).json()
    # A plan attaches to a buy only.
    client.post(
        "/v1/trades", json={"ticker": "AAPL", "side": "buy", "quantity": "1"}, headers=_h(uid)
    )
    sell = client.post(
        "/v1/trades",
        json={"ticker": "AAPL", "side": "sell", "quantity": "1", "trade_plan_id": plan["id"]},
        headers=_h(uid),
    )
    assert sell.status_code == 422
    both = client.post(
        "/v1/trades",
        json={"ticker": "AAPL", "side": "buy", "quantity": "1", "trade_plan_id": plan["id"],
              "plan": PLAN},
        headers=_h(uid),
    )  # fmt: skip
    assert both.status_code == 422
    # Cancel an open plan; then it takes no order.
    cancelled = client.patch(
        f"/v1/plans/{plan['id']}", json={"status": "cancelled"}, headers=_h(uid)
    )
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    late = client.post(
        "/v1/trades",
        json={"ticker": "AAPL", "side": "buy", "quantity": "1", "trade_plan_id": plan["id"]},
        headers=_h(uid),
    )
    assert late.status_code == 409


def test_plans_are_per_user_and_per_book(session: Session, client: TestClient) -> None:
    _market(session)
    _market(session, "MSFT", "300")
    alice, bob = _user(session), _user(session)
    book_b = client.post("/v1/books", json={"name": "Swing"}, headers=_h(alice)).json()["id"]
    in_default = _plan(client, alice).json()
    in_b = _plan(client, alice, ticker="MSFT", book=book_b, planned_entry="300",
                 planned_stop="290", planned_target="330").json()  # fmt: skip
    assert in_b["book_id"] == book_b and in_default["book_id"] != book_b

    listed = client.get("/v1/plans", headers=_h(alice)).json()["plans"]
    assert {p["id"] for p in listed} == {in_default["id"], in_b["id"]}
    only_b = client.get(f"/v1/plans?book={book_b}", headers=_h(alice)).json()["plans"]
    assert [p["id"] for p in only_b] == [in_b["id"]]
    assert client.get("/v1/plans?status=active", headers=_h(alice)).json()["plans"] == []
    assert [
        p["id"] for p in client.get("/v1/plans?ticker=MSFT", headers=_h(alice)).json()["plans"]
    ] == [in_b["id"]]

    # Another user sees none of it.
    assert client.get("/v1/plans", headers=_h(bob)).json()["plans"] == []
    assert client.get(f"/v1/plans/{in_b['id']}", headers=_h(bob)).status_code == 404
    assert (
        client.patch(f"/v1/plans/{in_b['id']}", json={"notes": "x"}, headers=_h(bob)).status_code
        == 404
    )
    assert client.delete(f"/v1/plans/{in_b['id']}", headers=_h(bob)).status_code == 404
    assert client.get(f"/v1/plans?book={book_b}", headers=_h(bob)).status_code == 404
    stolen = client.post(
        "/v1/trades",
        json={"ticker": "MSFT", "side": "buy", "quantity": "1", "trade_plan_id": in_b["id"]},
        headers=_h(bob),
    )
    assert stolen.status_code == 404
    # A plan in book B can't link an order in the default book.
    wrong_book = client.post(
        "/v1/trades",
        json={"ticker": "MSFT", "side": "buy", "quantity": "1", "trade_plan_id": in_b["id"]},
        headers=_h(alice),
    )
    assert wrong_book.status_code == 422
    right = client.post(
        f"/v1/trades?book={book_b}",
        json={"ticker": "MSFT", "side": "buy", "quantity": "1", "trade_plan_id": in_b["id"]},
        headers=_h(alice),
    )
    assert right.status_code == 201
    # An open plan can be deleted; deleting the book deletes its plans.
    assert client.delete(f"/v1/plans/{in_default['id']}", headers=_h(alice)).status_code == 204
    client.patch(f"/v1/books/{book_b}", json={"archived": True}, headers=_h(alice))
    assert client.delete(f"/v1/books/{book_b}", headers=_h(alice)).status_code == 204
    assert session.exec(select(TradePlan)).all() == []


def test_hidden_drill_plans_stay_out_of_the_plans_list(
    session: Session, client: TestClient
) -> None:
    from tests.test_drills import _deck, _seed

    _seed(session, "DRLX", seed=1)
    _seed(session, "QZPM", seed=2)
    uid = _user(session)
    deck = _deck(client, uid, k=1, seed=3, **{"from": "2022-02-01"}, to="2023-06-30")
    did = deck["drills"][0]["id"]
    put = client.put(f"/v1/drills/{did}/plan", headers=_h(uid),
                     json={"planned_entry": "100", "planned_stop": "90", "planned_size": "5"})  # fmt: skip
    assert put.status_code == 200
    plan = session.exec(select(TradePlan)).one()
    assert plan.source == "drill" and plan.why is None
    # Anonymised and not revealed: not listed, 404 by id (it names the symbol).
    assert client.get("/v1/plans", headers=_h(uid)).json()["plans"] == []
    assert client.get(f"/v1/plans/{plan.id}", headers=_h(uid)).status_code == 404
    client.post(f"/v1/drills/{did}/reveal", headers=_h(uid))
    listed = client.get("/v1/plans?source=drill", headers=_h(uid)).json()["plans"]
    assert [p["id"] for p in listed] == [plan.id] and listed[0]["status"] == "cancelled"
    # Read only here: the drill's plan form owns it.
    edit = client.patch(f"/v1/plans/{plan.id}", json={"notes": "x"}, headers=_h(uid))
    assert edit.status_code == 409
