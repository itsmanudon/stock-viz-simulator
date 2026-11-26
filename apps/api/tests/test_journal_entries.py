"""A5.5 (M10.3): journal entries, round trips across paper, imported and replay.

The done-when: an imported trade pairs with its locked plan and shows MAE,
MFE and R matching a hand calculation from the seeded daily bars. Also: a
plan written after entry, a replay entry (its MAE and MFE equal replay
forensics'), an open paper entry, grouping (partials, re-entries), the
rebuild after an import delete, venue session dates for XNSE (journal, P&L
calendar and chart markers), the news windows, R on fill markers, and
isolation. Every fixture is synthetic.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlmodel import Session, col, select

from stockviz.models import (
    AegisDocument,
    AegisDocumentEntity,
    AegisMapping,
    PriceBar,
    Symbol,
    Trade,
)
from stockviz.models.journal_entry import JournalEntry, JournalEntryFill
from stockviz.models.trade_plan import TradePlan
from stockviz.services.journal.roundtrips import (
    Bar,
    LedgerFill,
    excursions,
    group_round_trips,
    r_multiple,
    trade_figures,
)
from tests.test_imports import _book, _commit, _csv, _h, _row, _symbols, _user

T = "RELIANCE.NS"


def _bar(session: Session, ticker: str, day: date, o: str, h: str, lo: str, c: str) -> None:
    session.add(
        PriceBar(
            ticker=ticker, ts=datetime.combine(day, datetime.min.time()), interval="1d",
            open=Decimal(o), high=Decimal(h), low=Decimal(lo), close=Decimal(c),
            volume=1000, source="test",
        )
    )  # fmt: skip
    session.commit()


def _reliance_week(session: Session) -> None:
    """Mon 5 May to Fri 9 May 2025, every one an XNSE session."""
    _bar(session, T, date(2025, 5, 5), "1195", "1215", "1185", "1210")
    _bar(session, T, date(2025, 5, 6), "1210", "1230", "1190", "1225")
    _bar(session, T, date(2025, 5, 7), "1225", "1260", "1170", "1250")
    _bar(session, T, date(2025, 5, 8), "1250", "1310", "1240", "1300")
    _bar(session, T, date(2025, 5, 9), "1300", "1500", "1000", "1350")  # after the exit


def _plan(client: TestClient, uid: int, book: int, **extra) -> dict:
    body = {
        "ticker": T,
        "planned_entry": "1200",
        "planned_stop": "1100",
        "planned_target": "1400",
        "planned_size": "10",
        **extra,
    }
    r = client.post(f"/v1/plans?book={book}", json=body, headers=_h(uid))
    assert r.status_code == 201, r.text
    return r.json()


def _backdate_plan(session: Session, plan_id: int, when: datetime) -> None:
    row = session.get(TradePlan, plan_id)
    assert row is not None
    row.created_at = when
    session.add(row)
    session.commit()


def _entries(client: TestClient, uid: int, query: str = "") -> dict:
    r = client.get(f"/v1/journal/entries{query}", headers=_h(uid))
    assert r.status_code == 200, r.text
    return r.json()


def _imported_round_trip(session: Session, client: TestClient) -> tuple[int, int, dict]:
    _symbols(session)
    _reliance_week(session)
    uid = _user(session)
    book = _book(client, uid)
    plan = _plan(client, uid, book)
    _backdate_plan(session, plan["id"], datetime(2025, 5, 2, 12))
    body = _csv(
        _row("RELIANCE", "2025-05-05", "buy", "10", "1200", "T1", time="09:30:00"),
        _row("RELIANCE", "2025-05-08", "sell", "10", "1300", "T2", time="10:15:00"),
    )
    assert _commit(client, uid, book, body).status_code == 200
    return uid, book, plan


# --- the done-when -----------------------------------------------------------------------


def test_done_when_an_imported_trade_pairs_with_its_locked_plan(
    session: Session, client: TestClient
) -> None:
    uid, book, plan = _imported_round_trip(session, client)
    listed = _entries(client, uid, f"?book={book}")
    assert listed["total"] == 1
    entry = listed["entries"][0]
    assert entry["source"] == "imported" and entry["status"] == "closed"
    assert entry["book_id"] == book and entry["ticker"] == T and entry["currency"] == "INR"
    assert entry["venue"] == "XNSE"
    assert entry["entry_date"] == "2025-05-05" and entry["exit_date"] == "2025-05-08"

    # Paired automatically with the plan written before the buy, locked at the buy.
    session.expire_all()
    row = session.get(TradePlan, plan["id"])
    assert row is not None and not row.written_after_entry
    assert row.locked_at == datetime(2025, 5, 5, 4, 0)  # 09:30 IST
    assert entry["plan"]["id"] == plan["id"]
    assert entry["plan"]["label"] == "locked" and entry["plan"]["counts_for_adherence"]

    # Hand calculation. Average cost 1200 (one buy of 10). Approximate basis:
    # the entry day (5 May) and the exit day (8 May) count their whole range;
    # 9 May is after the exit and never counts.
    #   MAE: the lowest low while held is 1170 (7 May): -30 a share, -2.5%,
    #        -300 on 10 shares, -300 / initial risk 1000 = -0.3 R.
    #   MFE: the highest high is 1310 (8 May, the exit day's whole range):
    #        +110 a share, 9.1667%, +1100, 1.1 R.
    exc = entry["excursions"]
    assert exc["basis"] == "approximate_daily"
    assert "may include moves before entry or after exit" in exc["note"]
    mae, mfe = exc["mae"], exc["mfe"]
    assert Decimal(mae["per_share"]) == Decimal("-30")
    assert Decimal(mae["pct"]) == Decimal("-2.5000")
    assert Decimal(mae["amount"]) == Decimal("-300")
    assert mae["date"] == "2025-05-07" and Decimal(mae["price"]) == Decimal("1170")
    assert mae["r"] == -0.3
    assert Decimal(mfe["per_share"]) == Decimal("110")
    assert Decimal(mfe["pct"]) == Decimal("9.1667")
    assert Decimal(mfe["amount"]) == Decimal("1100")
    assert mfe["date"] == "2025-05-08" and mfe["r"] == 1.1

    # R = net P&L (gross 1000 less the estimated charges) / ((1200 - 1100) x 10).
    trades = session.exec(select(Trade).where(col(Trade.portfolio_id) == book)).all()
    fees = sum((t.fees or Decimal(0)) for t in trades)
    assert fees > 0  # the A4.2 NSE delivery schedule, estimated
    net = Decimal(1000) - fees
    assert Decimal(entry["net_pnl"]) == net
    assert entry["fees_estimated"] is True
    assert Decimal(entry["initial_risk"]) == Decimal(1000)
    assert entry["r_multiple"] == round(float(net / 1000), 4)
    assert Decimal(entry["avg_entry"]) == Decimal(1200)
    assert Decimal(entry["avg_exit"]) == Decimal(1300)
    assert Decimal(entry["quantity"]) == Decimal(10)
    assert entry["holding_days"] == 3 and entry["holding_sessions"] == 4

    detail = client.get(f"/v1/journal/entries/{entry['id']}", headers=_h(uid)).json()
    assert [f["side"] for f in detail["fills"]] == ["buy", "sell"]
    assert all(f["fees_estimated"] and f["time_known"] for f in detail["fills"])
    # Plan adherence (the drill's rule): entry at 1200 within 2%, size 10 of 10;
    # no close at or below 1100, so the stop was never tested.
    checks = {c["key"]: c["status"] for c in detail["adherence"]["checks"]}
    assert checks == {"entry": "passed", "stop": "not_applicable", "size": "passed"}
    assert detail["adherence"]["followed_plan"] is True


def test_a_plan_written_after_entry_is_shown_but_not_counted(
    session: Session, client: TestClient
) -> None:
    _symbols(session)
    _reliance_week(session)
    uid = _user(session)
    book = _book(client, uid)
    buy = _csv(_row("RELIANCE", "2025-05-05", "buy", "10", "1200", "T1", time="09:30:00"))
    _commit(client, uid, book, buy)
    plan = _plan(client, uid, book, link_open_position=True)
    assert plan["written_after_entry"] is True
    sell = _csv(_row("RELIANCE", "2025-05-08", "sell", "10", "1300", "T2", time="10:15:00"))
    _commit(client, uid, book, sell)
    entry = _entries(client, uid)["entries"][0]
    assert entry["plan"]["id"] == plan["id"]
    assert entry["plan"]["label"] == "written_after_entry"
    assert entry["plan"]["counts_for_adherence"] is False
    assert entry["r_multiple"] is not None  # shown
    detail = client.get(f"/v1/journal/entries/{entry['id']}", headers=_h(uid)).json()
    assert detail["adherence"] is None
    assert "not counted in plan adherence" in detail["adherence_note"]


def test_an_entry_without_a_plan_has_no_r(session: Session, client: TestClient) -> None:
    _symbols(session)
    _reliance_week(session)
    uid = _user(session)
    book = _book(client, uid)
    _commit(
        client,
        uid,
        book,
        _csv(
            _row("RELIANCE", "2025-05-05", "buy", "10", "1200", "T1"),
            _row("RELIANCE", "2025-05-08", "sell", "10", "1300", "T2"),
        ),
    )
    entry = _entries(client, uid)["entries"][0]
    assert entry["plan"] is None and entry["r_multiple"] is None
    assert entry["r_reason"] == "No plan is paired with this entry."
    assert entry["excursions"]["mae"]["r"] is None  # no stop, no R
    assert entry["excursions"]["mae"]["pct"] == "-2.5000"


# --- replay ------------------------------------------------------------------------------


def test_a_replay_entry_matches_replay_forensics(session: Session, client: TestClient) -> None:
    from tests.test_replay_forensics_router import DAY1, DAY4, _auth_headers, _make_user
    from tests.test_replay_forensics_router import _seed as seed_aapl

    seed_aapl(session)
    uid = _make_user(session, "journal-replay@stockviz.dev")
    h = _auth_headers(uid)
    sid = client.post(
        "/v1/replay/sessions",
        headers=h,
        json={"ticker": "AAPL", "start_at": DAY1, "end_at": DAY4, "starting_cash": "100000"},
    ).json()["id"]
    put = client.put(f"/v1/replay/sessions/{sid}/journal", headers=h, json={"thesis": "Base"})
    assert put.status_code == 200, put.text
    order = {"order_type": "market", "quantity": "1"}
    client.post(f"/v1/replay/sessions/{sid}/orders", headers=h, json={"side": "buy", **order})
    client.post(f"/v1/replay/sessions/{sid}/advance", headers=h)
    client.post(f"/v1/replay/sessions/{sid}/advance", headers=h)
    client.post(f"/v1/replay/sessions/{sid}/orders", headers=h, json={"side": "sell", **order})
    forensics = client.get(f"/v1/replay/sessions/{sid}/forensics", headers=h).json()
    episode = forensics["episodes"][0]

    listed = _entries(client, uid, "?source=replay")
    assert listed["total"] == 1
    entry = listed["entries"][0]
    assert entry["source"] == "replay" and entry["replay_session_id"] == sid
    assert entry["book_id"] is None and entry["status"] == "closed"
    exc = entry["excursions"]
    assert exc["basis"] == "exact_close"
    assert Decimal(exc["mae"]["pct"]) == Decimal(episode["mae_pct"]) == Decimal("-10")
    assert Decimal(exc["mfe"]["pct"]) == Decimal(episode["mfe_pct"]) == Decimal("10")
    assert Decimal(exc["mae"]["per_share"]) == Decimal(episode["mae_amount"])
    assert Decimal(entry["net_pnl"]) == Decimal(episode["realized_pnl"])
    # The session's plan pairs with its first round trip; a replay journal has no stop.
    assert entry["plan"]["label"] == "locked"
    assert entry["r_multiple"] is None
    assert entry["r_reason"] == "The plan has no stop, so there is no initial risk."
    # Book filters leave replay out; the book list of another user is 404.
    assert _entries(client, uid, "?source=paper")["total"] == 0


# --- paper: open entries, grouping, markers --------------------------------------------------


def _aapl(session: Session) -> None:
    if session.get(Symbol, "AAPL") is None:
        session.add(Symbol(ticker="AAPL", name="Apple", currency="USD"))
        session.commit()
    _bar(session, "AAPL", date(2025, 4, 10), "150", "150", "150", "150")


PLAN = {"planned_entry": "150", "planned_stop": "140", "planned_size": "10"}


def _trade(client: TestClient, uid: int, side: str, qty: str, **extra) -> dict:
    r = client.post(
        "/v1/trades", json={"ticker": "AAPL", "side": side, "quantity": qty, **extra},
        headers=_h(uid),
    )  # fmt: skip
    assert r.status_code == 201, r.text
    return r.json()


def test_an_open_paper_entry_is_marked_at_the_last_close(
    session: Session, client: TestClient
) -> None:
    _aapl(session)
    uid = _user(session)
    _trade(client, uid, "buy", "10", plan=PLAN)
    trade = session.exec(select(Trade)).one()
    trade.ts = datetime(2025, 4, 10, 18, 0)  # 14:00 New York
    session.add(trade)
    session.commit()
    _bar(session, "AAPL", date(2025, 4, 11), "150", "160", "145", "155")
    _bar(session, "AAPL", date(2025, 4, 14), "155", "158", "148", "152")

    entry = _entries(client, uid, "?status=open")["entries"][0]
    assert entry["source"] == "paper" and entry["status"] == "open"
    assert entry["exit_date"] is None and entry["as_of_date"] == "2025-04-14"
    assert Decimal(entry["mark_close"]) == Decimal(152)
    # (152 - 150) x 10 = 20, no US fees; R = 20 / ((150 - 140) x 10) = 0.2.
    assert Decimal(entry["unrealized_pnl"]) == Decimal(20)
    assert Decimal(entry["net_pnl"]) == Decimal(20)
    assert entry["r_multiple"] == 0.2
    assert entry["plan"]["label"] == "locked"
    exc = entry["excursions"]
    assert Decimal(exc["mae"]["per_share"]) == Decimal(-5)  # 145 on 11 Apr
    assert Decimal(exc["mfe"]["per_share"]) == Decimal(10)  # 160 on 11 Apr
    assert _entries(client, uid, "?status=closed")["total"] == 0


def test_a_missing_bar_makes_mae_and_mfe_unknown(session: Session, client: TestClient) -> None:
    _aapl(session)
    uid = _user(session)
    _trade(client, uid, "buy", "10")
    trade = session.exec(select(Trade)).one()
    trade.ts = datetime(2025, 4, 10, 18, 0)
    session.add(trade)
    session.commit()
    _bar(session, "AAPL", date(2025, 4, 14), "150", "151", "149", "150")  # 11 Apr missing
    exc = _entries(client, uid)["entries"][0]["excursions"]
    assert exc["mae"] is None and exc["mfe"] is None
    assert exc["missing_sessions"] == ["2025-04-11"]
    assert "unknown" in exc["reason"]


def test_partial_exits_stay_in_one_entry_and_a_reentry_opens_another(
    session: Session, client: TestClient
) -> None:
    _aapl(session)
    uid = _user(session)
    first = _trade(client, uid, "buy", "10", plan=PLAN)
    s1 = _trade(client, uid, "sell", "4")
    s2 = _trade(client, uid, "sell", "6")
    again = _trade(client, uid, "buy", "5")
    rows = _entries(client, uid)["entries"]
    assert [r["status"] for r in rows] == ["open", "closed"]  # newest first
    closed, reopened = rows[1], rows[0]
    assert closed["fills_count"] == 3 and reopened["fills_count"] == 1
    assert Decimal(closed["quantity"]) == Decimal(10)
    assert closed["plan"] is not None and reopened["plan"] is None
    links = session.exec(select(JournalEntryFill)).all()
    assert {link.trade_id for link in links} == {first["id"], s1["id"], s2["id"], again["id"]}

    # R on the chart's fill markers: the fill that closes the entry carries it;
    # the opening buy, the partial sell and the re-entry carry null.
    events = client.get("/v1/symbols/AAPL/events?types=fill", headers=_h(uid)).json()["events"]
    by_id = {e["ts"]: e for e in events}
    assert len(by_id) == 4
    trades = {t.id: t for t in session.exec(select(Trade)).all()}

    def marker(trade_id: int) -> dict:
        return by_id[trades[trade_id].ts.isoformat()]

    assert marker(s2["id"])["r_multiple"] == closed["r_multiple"] == 0.0
    assert marker(s2["id"])["closes_entry"] is True
    assert marker(s2["id"])["journal_entry_id"] == closed["id"]
    for tid in (first["id"], s1["id"], again["id"]):
        assert marker(tid)["r_multiple"] is None and marker(tid)["closes_entry"] is False


def test_pure_grouping_and_r() -> None:
    def fill(key: str, side: str, qty: str, price: str, day: int) -> LedgerFill:
        return LedgerFill(
            key=key, side=side, quantity=Decimal(qty), price=Decimal(price), fees=Decimal(0),
            at=datetime(2025, 1, day), venue_date=date(2025, 1, day),
        )  # fmt: skip

    trips = group_round_trips(
        [
            fill("s0", "sell", "1", "9", 1),  # flat: no entry
            fill("a", "buy", "10", "100", 2),
            fill("b", "buy", "10", "110", 3),
            fill("c", "sell", "5", "120", 6),
            fill("d", "sell", "15", "90", 7),
            fill("e", "buy", "3", "95", 8),
        ]
    )
    assert [t.key for t in trips] == ["a", "e"]
    assert trips[0].closed and not trips[1].closed
    figures = trade_figures(trips[0])
    # avg cost 105; realized 5 x 15 + 15 x -15 = -150.
    assert figures.avg_entry == Decimal(105) and figures.peak_quantity == Decimal(20)
    assert figures.net_pnl == Decimal(-150)
    r = r_multiple(figures, stop=Decimal(95), has_plan=True)
    assert r.initial_risk == Decimal(200) and r.value == -0.75
    bars = [
        Bar(date(2025, 1, d), Decimal(o), Decimal(h), Decimal(lo), Decimal(c))
        for d, o, h, lo, c in [
            (2, 100, 104, 96, 100),
            (3, 110, 112, 108, 110),
            (6, 120, 125, 115, 120),
            (7, 90, 92, 85, 90),
        ]
    ]
    approx = excursions(trips[0], bars, basis="approximate_daily", end_day=date(2025, 1, 7))
    # Day 2: cost 100 (20 not yet bought), low 96 -> -4; day 7: cost 105, low 85 -> -20.
    assert approx.mae is not None and approx.mae.per_share == Decimal(-20)
    assert approx.mfe is not None and approx.mfe.per_share == Decimal(20)  # 125 - 105
    exact = excursions(trips[0], bars, basis="exact_close", end_day=date(2025, 1, 7))
    # Exact: day 2 counts only its close (100 - 100 = 0).
    assert exact.mae is not None and exact.mae.per_share == Decimal(-20)


# --- the rebuild after an import delete ------------------------------------------------------


def test_entries_follow_an_import_delete_and_come_back_with_their_notes(
    session: Session, client: TestClient
) -> None:
    _symbols(session)
    _reliance_week(session)
    uid = _user(session)
    book = _book(client, uid)
    body = _csv(
        _row("RELIANCE", "2025-05-05", "buy", "10", "1200", "T1"),
        _row("RELIANCE", "2025-05-08", "sell", "10", "1300", "T2"),
    )
    batch = _commit(client, uid, book, body).json()["batch"]
    entry = _entries(client, uid)["entries"][0]
    patched = client.patch(
        f"/v1/journal/entries/{entry['id']}",
        json={"review_notes": "Sold into strength", "mistake_tags": ["early", "Early"]},
        headers=_h(uid),
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["review_notes"] == "Sold into strength"
    assert patched.json()["mistake_tags"] == ["early"]

    assert (
        client.delete(f"/v1/books/{book}/imports/{batch['id']}", headers=_h(uid)).status_code == 204
    )
    assert _entries(client, uid)["total"] == 0
    assert client.get(f"/v1/journal/entries/{entry['id']}", headers=_h(uid)).status_code == 404
    kept = session.get(JournalEntry, entry["id"])
    assert kept is not None and kept.status == "detached"  # it holds text
    assert session.exec(select(JournalEntryFill)).all() == []

    # The same file again: the same first fill, so the same entry and its notes.
    _commit(client, uid, book, body)
    back = _entries(client, uid)["entries"][0]
    assert back["id"] == entry["id"] and back["has_notes"] and back["mistake_tags"] == ["early"]
    assert back["status"] == "closed"


def test_an_entry_without_text_is_dropped_with_its_fills(
    session: Session, client: TestClient
) -> None:
    _symbols(session)
    _reliance_week(session)
    uid = _user(session)
    book = _book(client, uid)
    batch = _commit(
        client, uid, book, _csv(_row("RELIANCE", "2025-05-05", "buy", "10", "1200", "T1"))
    ).json()["batch"]
    assert _entries(client, uid)["total"] == 1
    client.delete(f"/v1/books/{book}/imports/{batch['id']}", headers=_h(uid))
    assert _entries(client, uid)["total"] == 0
    assert session.exec(select(JournalEntry)).all() == []


# --- venue session dates -----------------------------------------------------------------------


def test_xnse_fills_take_the_ist_date_in_the_journal_calendar_and_markers(
    session: Session, client: TestClient
) -> None:
    _symbols(session)
    _reliance_week(session)
    uid = _user(session)
    book = _book(client, uid)
    # No time in the file: the fill is dated at the start of the IST trade date,
    # 18:30 UTC the day before (13:30 or 14:30 in New York, the day before).
    _commit(
        client,
        uid,
        book,
        _csv(
            _row("RELIANCE", "2025-05-06", "buy", "10", "1200", "T1", time=""),
            _row("RELIANCE", "2025-05-08", "sell", "10", "1300", "T2", time=""),
        ),
    )
    sell = session.exec(select(Trade).where(col(Trade.side) == "sell")).one()
    assert sell.ts == datetime(2025, 5, 7, 18, 30)
    entry = _entries(client, uid)["entries"][0]
    assert entry["entry_date"] == "2025-05-06" and entry["exit_date"] == "2025-05-08"
    detail = client.get(f"/v1/journal/entries/{entry['id']}", headers=_h(uid)).json()
    assert [f["time_known"] for f in detail["fills"]] == [False, False]
    assert [f["venue_date"] for f in detail["fills"]] == ["2025-05-06", "2025-05-08"]

    # The P&L calendar puts the sell on 8 May (IST), not New York's 7 May.
    day = client.get(f"/v1/portfolio/journal/days/2025-05-08?book={book}", headers=_h(uid))
    assert day.status_code == 200 and day.json()["stats"]["trade_count"] == 1
    assert day.json()["executions"][0]["session_date"] == "2025-05-08"
    wrong = client.get(f"/v1/portfolio/journal/days/2025-05-07?book={book}", headers=_h(uid))
    assert wrong.json()["stats"]["trade_count"] == 0
    month = client.get(f"/v1/portfolio/journal/months/2025/5?book={book}", headers=_h(uid))
    assert [d["date"] for d in month.json()["days"]] == ["2025-05-08"]

    # Chart markers use the venue date too.
    events = client.get(
        f"/v1/symbols/{T}/events?types=fill&from=2025-05-01&to=2025-05-31", headers=_h(uid)
    ).json()["events"]
    assert [(e["date"], e["side"]) for e in events] == [
        ("2025-05-06", "buy"),
        ("2025-05-08", "sell"),
    ]


def test_r_on_the_imported_closing_fill_marker(session: Session, client: TestClient) -> None:
    uid, _book_id, _plan_row = _imported_round_trip(session, client)
    entry = _entries(client, uid)["entries"][0]
    events = client.get(
        f"/v1/symbols/{T}/events?types=fill&from=2025-05-01&to=2025-05-31", headers=_h(uid)
    ).json()["events"]
    buy, sell = events
    assert buy["r_multiple"] is None and buy["journal_entry_id"] == entry["id"]
    assert sell["r_multiple"] == entry["r_multiple"] and sell["closes_entry"] is True
    # Signed out: no fills at all.
    anon = client.get(f"/v1/symbols/{T}/events?from=2025-05-01&to=2025-05-31").json()
    assert all(e["type"] != "fill" for e in anon["events"])


# --- news at entry and exit ------------------------------------------------------------------


def _doc(session: Session, doc_id: str, at: datetime, ticker: str = T) -> None:
    entity = f"ent_{ticker}"
    if session.get(AegisMapping, f"map_{ticker}") is None:
        session.add(
            AegisMapping(
                mapping_id=f"map_{ticker}", entity_id=entity, scheme="provider_id",
                identifier=f"stockviz:{ticker}", created_at=datetime(2026, 1, 1),
            )
        )  # fmt: skip
    session.add(
        AegisDocument(
            document_id=doc_id, source_id="src", source_name="Wire", title=f"Headline {doc_id}",
            url=f"https://news.example.test/{doc_id}", first_seen_at=at, available_at=at,
            last_signed_at=at,
        )
    )  # fmt: skip
    session.flush()
    session.add(
        AegisDocumentEntity(
            document_id=doc_id, entity_id=entity, canonical_name=entity, kind="organization",
            resolution_analysis_id=f"res_{doc_id}", confidence=1.0,
        )
    )  # fmt: skip
    session.commit()


def test_news_at_entry_and_exit_windows(session: Session, client: TestClient) -> None:
    uid, _book_id, _plan_row = _imported_round_trip(session, client)
    ist = timedelta(hours=5, minutes=30)
    # Entry 5 May: three sessions before is Tue 29 Apr (1 May is a holiday).
    _doc(session, "early", datetime(2025, 4, 25, 10) - ist)  # before the window
    _doc(session, "pre", datetime(2025, 4, 29, 9) - ist)  # first day of the window
    _doc(session, "entry-day", datetime(2025, 5, 5, 23, 59) - ist)  # last minute
    _doc(session, "next", datetime(2025, 5, 6, 0, 1) - ist)  # after the entry day
    # Exit 8 May: from 7 May to the session after, 9 May.
    _doc(session, "after", datetime(2025, 5, 9, 15) - ist)
    _doc(session, "late", datetime(2025, 5, 12, 10) - ist)
    _doc(session, "other", datetime(2025, 5, 5, 10) - ist, ticker="TCS.NS")
    entry = _entries(client, uid)["entries"][0]
    detail = client.get(f"/v1/journal/entries/{entry['id']}", headers=_h(uid)).json()
    at_entry = detail["news_at_entry"]
    assert at_entry["from_date"] == "2025-04-29" and at_entry["to_date"] == "2025-05-05"
    assert at_entry["coverage"] == "covered"
    assert {h["id"] for h in at_entry["headlines"]} == {"pre", "entry-day"}
    head = next(h for h in at_entry["headlines"] if h["id"] == "entry-day")
    assert head["date"] == "2025-05-05" and head["source"] == "Wire" and head["url"]
    assert "text" not in head and "body" not in head
    at_exit = detail["news_at_exit"]
    assert at_exit["from_date"] == "2025-05-07" and at_exit["to_date"] == "2025-05-09"
    assert {h["id"] for h in at_exit["headlines"]} == {"after"}


def test_news_before_the_first_document_says_no_news_copy(
    session: Session, client: TestClient
) -> None:
    uid, _book_id, _plan_row = _imported_round_trip(session, client)
    _doc(session, "much-later", datetime(2026, 1, 5, 10))
    entry = _entries(client, uid)["entries"][0]
    detail = client.get(f"/v1/journal/entries/{entry['id']}", headers=_h(uid)).json()
    assert detail["news_at_entry"]["coverage"] == "before_news_copy"
    assert detail["news_at_entry"]["note"].startswith("No news copy for this date")
    assert detail["news_at_entry"]["headlines"] == []


# --- isolation and the patch ------------------------------------------------------------------


def test_entries_are_private(session: Session, client: TestClient) -> None:
    uid, book, _plan_row = _imported_round_trip(session, client)
    entry = _entries(client, uid)["entries"][0]
    other = _user(session)
    assert _entries(client, other)["total"] == 0
    assert client.get(f"/v1/journal/entries/{entry['id']}", headers=_h(other)).status_code == 404
    stolen = client.patch(
        f"/v1/journal/entries/{entry['id']}", json={"lessons": "x"}, headers=_h(other)
    )
    assert stolen.status_code == 404
    assert client.get(f"/v1/journal/entries?book={book}", headers=_h(other)).status_code == 404
    assert client.get("/v1/journal/entries").status_code == 401
    assert client.get(f"/v1/journal/entries/{entry['id']}", headers=_h(uid)).status_code == 200


def test_filters_and_patch_rules(session: Session, client: TestClient) -> None:
    uid, book, _plan_row = _imported_round_trip(session, client)
    entry = _entries(client, uid)["entries"][0]
    eid = entry["id"]
    assert _entries(client, uid, "?book=all")["total"] == 1
    assert _entries(client, uid, "?source=imported&status=closed&ticker=reliance.ns")["total"] == 1
    assert _entries(client, uid, "?from=2025-05-06")["total"] == 0
    assert _entries(client, uid, "?to=2025-05-05")["total"] == 1
    assert (
        client.get("/v1/journal/entries?from=2025-05-06&to=2025-05-01", headers=_h(uid)).status_code
        == 400
    )
    too_many = client.patch(
        f"/v1/journal/entries/{eid}", json={"setup_tags": [f"t{i}" for i in range(13)]},
        headers=_h(uid),
    )  # fmt: skip
    assert too_many.status_code == 422
    long_tag = client.patch(
        f"/v1/journal/entries/{eid}", json={"setup_tags": ["x" * 33]}, headers=_h(uid)
    )
    assert long_tag.status_code == 422
    unknown = client.patch(f"/v1/journal/entries/{eid}", json={"net_pnl": "1"}, headers=_h(uid))
    assert unknown.status_code == 422  # figures are never written
    ok = client.patch(
        f"/v1/journal/entries/{eid}",
        json={"setup_tags": ["Breakout"], "lessons": "  Size up  ", "mistakes": "Chased"},
        headers=_h(uid),
    ).json()
    assert ok["lessons"] == "Size up" and ok["setup_tags"] == ["Breakout"]
    assert _entries(client, uid, "?tag=breakout")["total"] == 1
    assert _entries(client, uid, "?tag=other")["total"] == 0
    cleared = client.patch(f"/v1/journal/entries/{eid}", json={"mistakes": ""}, headers=_h(uid))
    assert cleared.json()["mistakes"] is None
    # The plan's setup filters too.
    assert _entries(client, uid, "?setup_version_id=999999")["total"] == 0
    assert book  # the book list filter was checked above


def test_the_fill_time_converts_to_the_venue_date() -> None:
    from stockviz.services.journal.entries import venue_session_date

    late_utc = datetime(2025, 5, 7, 18, 30)  # 00:00 IST on 8 May
    assert venue_session_date(late_utc, T) == date(2025, 5, 8)
    assert venue_session_date(late_utc, "AAPL") == date(2025, 5, 7)
    assert venue_session_date(datetime(2025, 5, 8, 2, 0, tzinfo=UTC), "AAPL") == date(2025, 5, 7)
