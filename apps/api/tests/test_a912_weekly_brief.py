"""A9.12 (M11.6): the weekly journal review and the morning brief."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from fastapi.testclient import TestClient
from sqlmodel import Session

from stockviz.models import Notification, Watchlist, WatchlistItem
from stockviz.services.brief import morning_brief
from stockviz.services.journal.edge import Outcome
from stockviz.services.journal.weekly import review
from tests.symbols import seed_symbols
from tests.test_a35_chart_context import _bars
from tests.test_a84_hybrid_search import _doc
from tests.test_drills import _auth, _user

WEEK_END = date(2026, 11, 27)


def _o(i: int, closed: date, net: float, *, r: float | None = None, followed: bool | None = True,
       size: float = 1000.0, tags: tuple[str, ...] = (), currency: str = "USD",
       source: str = "paper") -> Outcome:  # fmt: skip
    at = datetime.combine(closed, datetime.min.time())
    return Outcome(
        entry_id=i, source=source, currency=currency, net_pnl=net, r=r, holding_days=1,
        followed_plan=followed, fees_estimated=False, closed_at=at + timedelta(hours=15),
        entry_date=closed, mistake_tags=tags, entry_notional=size, opened_at=at + timedelta(hours=10),
    )  # fmt: skip


def test_an_empty_week() -> None:
    r = review([], WEEK_END)
    assert r.week.entries == 0 and r.look_at == [] and r.notes == ["No entry closed this week."]
    assert r.week_start == date(2026, 11, 21)


def test_the_rules_name_their_entries() -> None:
    base = [_o(i, WEEK_END - timedelta(days=8 + i), 50.0, r=1.0) for i in range(8)]
    week = [
        _o(100, date(2026, 11, 23), -40.0, r=-1.0),
        _o(101, date(2026, 11, 24), -30.0, r=-0.8, followed=False, tags=("late entry",)),
        _o(102, date(2026, 11, 25), -20.0, r=-0.4, followed=None, tags=("Late Entry",)),
        _o(103, date(2026, 11, 26), -10.0, r=-0.2, size=5000.0),  # after a losing close, 5x
        _o(104, date(2026, 11, 27), 5.0, r=0.1, currency="INR"),
    ]
    r = review(base + week, WEEK_END)
    assert r.week.entries == 5 and r.week.wins == 1 and r.week.losses == 4
    assert r.week.net_by_currency == {"USD": -100.0, "INR": 5.0}
    assert r.baseline_entries_per_week == 2.0 and r.baseline_mean_r == 1.0
    keys = [i.key for i in r.look_at]
    assert keys == ["tilt", "plan_not_followed", "no_plan", "mistake_tag", "r_below_baseline",
                    "more_entries"]  # fmt: skip
    by = {i.key: i for i in r.look_at}
    assert by["tilt"].entry_ids == (103,) and by["plan_not_followed"].entry_ids == (101,)
    assert by["no_plan"].entry_ids == (102,)
    assert '"late entry" 2 times' in by["mistake_tag"].text
    assert any("per currency" in n for n in r.notes)
    for item in r.look_at:  # neutral wording
        assert not any(w in item.text.lower() for w in ("buy", "sell", "bad", "good"))


def test_replay_entries_are_not_counted_as_unplanned() -> None:
    r = review([_o(1, WEEK_END, 10.0, followed=None, source="replay")], WEEK_END)
    assert r.week.no_plan == 0 and all(i.key != "no_plan" for i in r.look_at)
    assert "a record, not a pattern" in r.notes[0]


def test_weekly_route(client: TestClient, session: Session) -> None:
    uid = _user(session, "w@stockviz.dev")
    assert client.get("/v1/journal/weekly").status_code == 401
    got = client.get("/v1/journal/weekly", params={"week_end": "2026-11-27"}, headers=_auth(uid))
    assert got.status_code == 200, got.text
    body = got.json()
    assert body["week_start"] == "2026-11-21" and body["week"]["entries"] == 0
    assert "not a judgement of skill" in body["method"]


def test_morning_brief(client: TestClient, session: Session) -> None:
    seed_symbols(session, "AAPL", "MSFT", "KO")
    uid = _user(session, "b@stockviz.dev")
    other = _user(session, "o@stockviz.dev")
    wl = Watchlist(user_id=uid, name="Main", is_default=True)
    session.add(wl)
    session.commit()
    from stockviz.services.instruments import instrument_ids

    ids = instrument_ids(session, ["AAPL", "MSFT", "KO"])
    for t in ("AAPL", "MSFT"):
        session.add(WatchlistItem(watchlist_id=wl.id or 0, ticker=t, instrument_id=ids[t]))
    session.commit()
    _bars(session, "AAPL", [100.0, 103.0], date(2026, 11, 24))
    _bars(session, "MSFT", [200.0, 198.0], date(2026, 11, 24))
    _bars(session, "KO", [50.0, 60.0], date(2026, 11, 24))  # not watched
    now = datetime(2026, 11, 27, 6)
    session.add(Notification(user_id=uid, category="alert", title="AAPL above 102", body="Fired.",
                             source_key="a1", created_at=now - timedelta(hours=3)))  # fmt: skip
    session.add(Notification(user_id=uid, category="alert", title="old", body="Old.",
                             source_key="a2", created_at=now - timedelta(days=3)))  # fmt: skip
    session.add(Notification(user_id=other, category="alert", title="not mine", body="x",
                             source_key="a3", created_at=now - timedelta(hours=1)))  # fmt: skip
    session.commit()
    _doc(session, "AAPL", "AAPL 8-K", "Results were released today for the quarter.",
         now - timedelta(days=2))  # fmt: skip
    b = morning_brief(session, uid, now=now)
    assert b.symbols == ["AAPL", "MSFT"]
    assert [(m.ticker, m.change_pct) for m in b.moves] == [("AAPL", 3.0), ("MSFT", -1.0)]
    assert b.moves[0].close_date == date(2026, 11, 25) and not b.moves[0].held
    assert [a.title for a in b.alerts] == ["AAPL above 102"]
    assert [(d.title, t) for d, t in b.documents] == [("AAPL 8-K", "AAPL")]
    assert morning_brief(session, other, now=now).symbols == []
    res = client.get("/v1/brief", headers=_auth(uid))
    assert res.status_code == 200 and res.json()["moves"][0]["ticker"] == "AAPL"
    assert "end of day" in res.json()["note"]
