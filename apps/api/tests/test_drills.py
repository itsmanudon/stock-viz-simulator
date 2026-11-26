"""A4.7 (M9.3): drills and decks.

The design note's acceptance (section 3): a drill deck's trigger dates are
exactly the dates where the rule's vector series turned true
(``test_acceptance_*``). Also: sampling by seed, the lag skip, anonymised
responses that never name the ticker, the company or a real date of the
drill, the date shift keeping weekdays, the plan gate and the process score,
reveal, deletion and user isolation.
"""

from __future__ import annotations

import json
import random
import re
from datetime import date, datetime, timedelta
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from jose import jwt as jose_jwt
from sqlmodel import Session, select

from stockviz.models import (
    AegisDocument,
    AegisDocumentEntity,
    AegisMapping,
    Drill,
    DrillDeck,
    PriceBar,
    ReplaySession,
    Setup,
    SetupVersion,
    Symbol,
    User,
)
from stockviz.schemas import DrillDeckIn, ScanEventStudyIn
from stockviz.services.drills import decks
from stockviz.services.drills.anonymise import Mask, label_for
from stockviz.services.drills.score import BarFacts, FillFacts, PlanFacts, score_drill
from stockviz.services.drills.triggers import offset_weeks
from stockviz.services.dsl import compile_rule, load_symbol, vector
from stockviz.services.scan_event_study import run_scan_event_study
from stockviz.settings import get_settings

SECRET = get_settings().internal_api_token
RULE = "close crosses_above sma(close, 20)"
START = datetime(2022, 1, 3)
NAMES = {"DRLX": "Drillex Holdings", "QZPM": "Quazipam Industries"}


def _auth(user_id: int) -> dict[str, str]:
    token = jose_jwt.encode({"sub": str(user_id)}, SECRET, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


def _user(session: Session, email: str = "a47@stockviz.dev") -> int:
    row = User(email=email, name="A47")
    session.add(row)
    session.commit()
    assert row.id is not None
    return row.id


def _days(n: int, start: datetime = START) -> list[datetime]:
    out, day = [], start
    while len(out) < n:
        if day.weekday() < 5:
            out.append(day)
        day += timedelta(days=1)
    return out


def _seed(
    session: Session,
    ticker: str,
    n: int = 400,
    *,
    seed: int = 1,
    currency: str = "USD",
    start: datetime = START,
) -> list[datetime]:
    session.add(
        Symbol(
            ticker=ticker,
            name=NAMES.get(ticker, f"{ticker} Corp"),
            sector="Industrials",
            currency=currency,
        )
    )
    session.commit()
    rng = np.random.default_rng(seed)
    closes = 100 * np.exp(np.cumsum(rng.normal(0, 0.02, n)))
    days = _days(n, start)
    for ts, c in zip(days, closes, strict=True):
        close = Decimal(str(round(float(c), 2)))
        session.add(
            PriceBar(
                ticker=ticker, ts=ts, interval="1d", open=close, high=close + 1,
                low=max(close - 1, Decimal("0.5")), close=close, volume=100_000, source="test",
            )
        )  # fmt: skip
    session.commit()
    return days


def _edges(session: Session, ticker: str, start: date, end: date) -> list[tuple[str, date]]:
    """The vector series' false-to-true dates, computed here independently."""
    rule = compile_rule(RULE)
    data = load_symbol(session, ticker, end=end, needs=rule.needs)
    series = vector(rule, data)
    out = []
    prev = None
    for ts, value in series.items():
        day = ts.date()  # pyright: ignore[reportAttributeAccessIssue]
        cur = None if pd.isna(value) else bool(value)
        if cur is True and prev is False and start <= day <= end:
            out.append((ticker, day))
        prev = cur
    return out


def _deck(client: TestClient, uid: int, **body) -> dict:
    payload = {"rule": {"rule": RULE}, "universe": {"tickers": ["DRLX", "QZPM"]}, **body}
    res = client.post("/v1/drills/decks", json=payload, headers=_auth(uid))
    assert res.status_code == 201, res.text
    return res.json()


def _deck_triggers(session: Session, deck_id: int) -> list[tuple[str, date]]:
    rows = session.exec(select(Drill).where(Drill.deck_id == deck_id)).all()
    return [(d.ticker, d.trigger_date) for d in sorted(rows, key=lambda d: d.position)]


# --- the acceptance: trigger dates are the vector series' edges -----------------


def test_acceptance_deck_triggers_equal_the_vector_edges(
    session: Session, client: TestClient
) -> None:
    _seed(session, "DRLX", seed=1)
    _seed(session, "QZPM", seed=2)
    uid = _user(session)
    full = sorted(
        _edges(session, "DRLX", date(2022, 1, 1), date(2024, 12, 31))
        + _edges(session, "QZPM", date(2022, 1, 1), date(2024, 12, 31)),
        key=lambda t: (t[1], t[0]),
    )
    assert len(full) > 25
    # A range holding exactly 20 edges (both ends are edges), so K=25 >= all.
    lo, hi = full[3][1], full[22][1]
    expected = {t for t in full if lo <= t[1] <= hi}
    assert 18 <= len(expected) <= 25
    deck = _deck(client, uid, k=25, **{"from": lo.isoformat()}, to=hi.isoformat())
    got = _deck_triggers(session, deck["id"])
    assert set(got) == expected
    assert len(got) == len(expected) == deck["triggers_found"] == deck["triggers_eligible"]
    # The scan event study counts the same events over the same range.
    study = run_scan_event_study(
        session,
        ScanEventStudyIn.model_validate(
            {
                "trigger": {"rule": RULE},
                "universe": {"tickers": ["DRLX", "QZPM"]},
                "from": lo.isoformat(),
                "to": hi.isoformat(),
                "horizons": [1],
            }
        ),
        user_id=uid,
    )
    assert study.events_found == len(expected)

    # K below the count: an exact subset of the edges.
    small = _deck(client, uid, k=5, **{"from": lo.isoformat()}, to=hi.isoformat())
    sub = _deck_triggers(session, small["id"])
    assert len(sub) == 5 and len(set(sub)) == 5 and set(sub) <= expected


def test_drill_sessions_open_at_the_trigger_with_the_lead_in(
    session: Session, client: TestClient
) -> None:
    days = _seed(session, "DRLX", seed=1)
    _seed(session, "QZPM", seed=2)
    uid = _user(session)
    deck = _deck(client, uid, k=5, lead_bars=30, follow_bars=10, anonymised=False,
                 **{"from": "2022-06-01"}, to="2023-06-01")  # fmt: skip
    for row in session.exec(select(Drill).where(Drill.deck_id == deck["id"])).all():
        replay = session.get(ReplaySession, row.session_id)
        assert replay is not None
        i = days.index(row.trigger_at)
        assert replay.current_at == row.trigger_at
        assert replay.start_at == days[max(0, i - 30)]
        assert replay.end_at == days[min(len(days) - 1, i + 10)]


# --- sampling by seed -------------------------------------------------------------


def test_sampling_is_reproducible_by_seed(session: Session, client: TestClient) -> None:
    _seed(session, "DRLX", seed=1)
    _seed(session, "QZPM", seed=2)
    uid = _user(session)
    window = {"from": "2022-03-01", "to": "2024-06-28"}
    a = _deck(client, uid, k=6, seed=1234, **window)
    b = _deck(client, uid, k=6, seed=1234, **window)
    c = _deck(client, uid, k=6, seed=99, **window)
    assert a["seed"] == b["seed"] == 1234
    ta, tb, tc = (_deck_triggers(session, d["id"]) for d in (a, b, c))
    assert ta == tb
    assert ta != tc
    # The draw is random.Random(seed).sample over the eligible triggers sorted
    # by (date, ticker).
    eligible = sorted(
        _edges(session, "DRLX", date(2022, 3, 1), date(2024, 6, 28))
        + _edges(session, "QZPM", date(2022, 3, 1), date(2024, 6, 28)),
        key=lambda t: (t[1], t[0]),
    )
    assert ta == random.Random(1234).sample(eligible, 6)
    # No seed: one is drawn and stored.
    d = _deck(client, uid, k=3, **window)
    assert isinstance(d["seed"], int)


# --- the lag ----------------------------------------------------------------------


def test_indian_triggers_inside_the_lag_are_skipped_and_counted(session: Session) -> None:
    days = _seed(session, "ZQRT.NS", n=300, seed=3, currency="INR")
    uid = _user(session)
    last = days[-1].date()
    today = last + timedelta(days=10)  # the last 20 days of bars sit inside the lag
    body = DrillDeckIn.model_validate(
        {"rule": {"rule": RULE}, "universe": {"tickers": ["ZQRT.NS"]}, "k": 25,
         "follow_bars": 5, "from": days[30].date().isoformat(), "to": last.isoformat()}
    )  # fmt: skip
    edges = _edges(session, "ZQRT.NS", days[30].date(), last)
    cutoff = today - timedelta(days=30)
    index = {d.date(): i for i, d in enumerate(days)}
    inside = [t for t in edges if days[min(len(days) - 1, index[t[1]] + 5)].date() > cutoff]
    assert inside, "the fixture needs a trigger near the end"
    deck = decks.create_deck(session, body, user_id=uid, today=today)
    assert deck.lag_skipped == len(inside)
    assert deck.triggers_found == len(edges)
    assert deck.triggers_eligible == len(edges) - len(inside)
    got = set(_deck_triggers(session, deck.id or 0))
    assert not got & set(inside)
    for row in session.exec(select(Drill).where(Drill.deck_id == deck.id)).all():
        replay = session.get(ReplaySession, row.session_id)
        assert replay is not None and replay.currency == "INR"
        assert replay.end_at.date() <= cutoff


# --- anonymisation ------------------------------------------------------------------


def _doc(session: Session, doc_id: str, ticker: str, at: datetime) -> None:
    entity = f"ent_{ticker}"
    if session.get(AegisMapping, f"map_{ticker}") is None:
        session.add(
            AegisMapping(
                mapping_id=f"map_{ticker}", entity_id=entity, scheme="provider_id",
                identifier=f"stockviz:{ticker}", created_at=datetime(2021, 1, 1),
            )
        )  # fmt: skip
    session.add(
        AegisDocument(
            document_id=doc_id, source_id="src", source_name="Drillex Wire",
            title=f"{NAMES[ticker]} ({ticker}) beats estimates {doc_id}",
            url=f"https://n.test/{ticker.lower()}/{doc_id}", first_seen_at=at,
            available_at=at, last_signed_at=at,
        )
    )  # fmt: skip
    session.flush()
    session.add(
        AegisDocumentEntity(
            document_id=doc_id, entity_id=entity, canonical_name=NAMES[ticker],
            kind="organization", resolution_analysis_id=f"r_{doc_id}", confidence=1.0,
        )
    )  # fmt: skip
    session.commit()


def _leaks(text: str, ticker: str, real_dates: set[str]) -> list[str]:
    found = []
    if re.search(rf"(?<![A-Za-z0-9]){re.escape(ticker)}(?![A-Za-z0-9])", text, re.IGNORECASE):
        found.append(ticker)
    if NAMES[ticker].lower() in text.lower():
        found.append(NAMES[ticker])
    found += sorted(d for d in real_dates if d in text)
    return found


def test_anonymised_responses_never_leak_ticker_name_or_real_dates(
    session: Session, client: TestClient
) -> None:
    days = _seed(session, "DRLX", seed=1)
    _seed(session, "QZPM", seed=2)
    for i in range(0, len(days), 7):  # news on many days, so drills see some
        _doc(session, f"d{i}", "DRLX", days[i] - timedelta(hours=3))
        _doc(session, f"q{i}", "QZPM", days[i] - timedelta(hours=3))
    uid = _user(session)
    h = _auth(uid)
    deck = _deck(client, uid, k=5, seed=7, **{"from": "2022-02-01"}, to="2023-06-30")
    responses: list[tuple[str, str]] = []
    news_seen = 0

    def keep(res) -> dict:
        assert res.status_code < 300, res.text
        responses.append((res.request.url.path, res.text))
        return res.json() if res.text else {}

    for row in deck["drills"]:
        assert row["ticker"] is None and row["trigger_date"] is None
        assert row["label"] == label_for(row["position"])
        drill = session.get(Drill, row["id"])
        assert drill is not None
        replay = session.get(ReplaySession, drill.session_id)
        assert replay is not None
        window = [d for d in days if replay.start_at <= d <= replay.end_at]
        real = {d.date().isoformat() for d in window}
        did = row["id"]
        responses.clear()
        keep(client.get(f"/v1/drills/{did}", headers=h))
        # The plan gates the first order.
        assert client.post(f"/v1/drills/{did}/orders", json={"side": "buy", "quantity": "1"},
                           headers=h).status_code == 409  # fmt: skip
        view = keep(client.get(f"/v1/drills/{did}", headers=h))
        close = Decimal(view["bar"]["close"])
        keep(client.put(f"/v1/drills/{did}/plan", headers=h, json={
            "planned_entry": str(close), "planned_stop": str(round(close * Decimal("0.95"), 2)),
            "planned_size": "10"}))  # fmt: skip
        keep(client.post(f"/v1/drills/{did}/orders", headers=h,
                         json={"side": "buy", "quantity": "10"}))  # fmt: skip
        keep(client.post(f"/v1/drills/{did}/orders", headers=h, json={
            "side": "sell", "order_type": "stop_loss", "quantity": "10",
            "limit_price": str(round(close * Decimal("0.95"), 2))}))  # fmt: skip
        # Errors are masked too (this one names the ticker in the replay route).
        res = client.post(f"/v1/drills/{did}/orders", headers=h,
                          json={"side": "sell", "quantity": "1000"})  # fmt: skip
        assert res.status_code == 422
        responses.append(("error", res.text))
        for _ in range(3):
            current = keep(client.get(f"/v1/drills/{did}", headers=h))["session"]["current_at"]
            keep(client.post(f"/v1/drills/{did}/advance", headers=h,
                             params={"expected_current_at": current}))  # fmt: skip
        keep(client.get(f"/v1/drills/{did}/indicators", headers=h,
                        params={"names": "sma_20,rsi_14,macd,bb_20_2"}))  # fmt: skip
        events = keep(client.get(f"/v1/drills/{did}/events", headers=h))
        for e in events["events"]:
            if e["type"] == "news":
                news_seen += 1
                assert e["headlines"] == [] and e["sources"] == [] and e["count"] >= 1
        shown = view["history"][-1]["ts"][:10]
        drawn = keep(client.post(f"/v1/drills/{did}/drawings", headers=h, json={
            "kind": "hline", "points": [{"ts": shown, "price": str(close)}]}))  # fmt: skip
        keep(client.patch(f"/v1/drills/{did}/drawings/{drawn['id']}", headers=h,
                          json={"label": "my line"}))  # fmt: skip
        keep(client.get(f"/v1/drills/{did}/drawings", headers=h))
        # The deck pages: the universe and the date range are the caller's own
        # input (a ticker list here), so they are left out of the check; the
        # drill rows must name neither the symbol nor a date.
        for res in (
            client.get(f"/v1/drills/decks/{deck['id']}", headers=h),
            client.get("/v1/drills/decks", headers=h),
        ):
            assert res.status_code == 200
            data = res.json()
            for d in data if isinstance(data, list) else [data]:
                for key in ("universe", "from", "to"):
                    d.pop(key)
            responses.append((res.request.url.path, json.dumps(data)))
        keep(client.get("/v1/replay/sessions", headers=h))
        for path, text in responses:
            assert not _leaks(text, drill.ticker, real), (path, _leaks(text, drill.ticker, real))
        # The replay routes do not serve an anonymised drill's session.
        for path in ("", "/market", "/history", "/forensics", "/events", "/summary", "/fills"):
            res = client.get(f"/v1/replay/sessions/{replay.id}{path}", headers=h)
            assert res.status_code == 404, path
        listed = client.get("/v1/replay/sessions", headers=h).json()
        assert replay.id not in [s["id"] for s in listed]
        # The stored drawing is on the real date.
        stored = client.get(f"/v1/drills/{did}/drawings", headers=h).json()["drawings"][0]
        assert stored["points"][0]["ts"] == shown
    assert news_seen > 0


def test_date_shift_is_whole_weeks_and_keeps_weekdays(session: Session, client: TestClient) -> None:
    days = _seed(session, "DRLX", seed=1)
    _seed(session, "QZPM", seed=2)
    uid = _user(session)
    deck = _deck(client, uid, k=5, seed=11, **{"from": "2022-02-01"}, to="2023-06-30")
    for row in deck["drills"]:
        drill = session.get(Drill, row["id"])
        assert drill is not None
        assert 52 <= abs(drill.date_offset_weeks) <= 520
        view = client.get(f"/v1/drills/{row['id']}", headers=_auth(uid)).json()
        replay = session.get(ReplaySession, drill.session_id)
        assert replay is not None
        real = [d for d in days if replay.start_at <= d <= replay.current_at]
        shown = [datetime.fromisoformat(b["ts"]).replace(tzinfo=None) for b in view["history"]]
        assert len(shown) == len(real)
        for s, r in zip(shown, real, strict=True):
            assert s.weekday() == r.weekday()
            assert (r - s) == timedelta(weeks=drill.date_offset_weeks)
        # Shown dates never pass today.
        assert shown[-1].date() <= date.today()


def test_offset_weeks_turns_a_later_shift_into_an_earlier_one_near_today() -> None:
    for position in range(25):
        assert offset_weeks(5, position, shown_end_limit=0) > 0


def test_mask_text_replaces_ticker_names_and_dates() -> None:
    mask = Mask("DRLX", "Stock A", 104, names=("Drillex Holdings",))
    assert mask.text("DRLX") == "Stock A"
    assert mask.text("Replay position 5 DRLX; on 2024-03-04") == (
        "Replay position 5 Stock A; on 2022-03-07"
    )
    assert "Drillex" not in mask.text("drillex holdings said")
    assert mask.text("DRLXY and ^DRLX stay") == "DRLXY and ^DRLX stay"


# --- plan and score ---------------------------------------------------------------


def _bars(closes: list[str]) -> list[BarFacts]:
    return [BarFacts(datetime(2024, 1, 1) + timedelta(days=i), Decimal(c)) for i, c in
            enumerate(closes)]  # fmt: skip


def _fill(side: str, qty: str, price: str, day: int) -> FillFacts:
    return FillFacts(side, Decimal(qty), Decimal(price), datetime(2024, 1, 1) + timedelta(days=day))


PLAN = PlanFacts(entry=Decimal(100), stop=Decimal(95), size=Decimal(10))


def test_score_no_trade_scores_nothing() -> None:
    s = score_drill(PLAN, [], _bars(["100", "90"]), total_pnl=Decimal(0))
    assert (s.traded, s.applicable, s.followed_plan, s.r_achieved) == (False, 0, None, None)


def test_score_followed_plan_with_stop_honoured() -> None:
    bars = _bars(["100", "98", "94", "93"])
    fills = [_fill("buy", "10", "100", 0), _fill("sell", "10", "94", 2)]
    s = score_drill(PLAN, fills, bars, total_pnl=Decimal(-60))
    by = {c.key: c.status for c in s.checks}
    assert by == {"entry": "passed", "stop": "passed", "size": "passed"}
    assert (s.passed, s.applicable, s.followed_plan) == (3, 3, True)
    assert s.r_achieved == pytest.approx(-60 / 50)  # (100 - 95) x 10 planned risk
    assert "not the score" in s.r_note


def test_score_stop_broken_entry_off_and_size_over() -> None:
    bars = _bars(["103", "96", "94", "92", "99"])
    fills = [_fill("buy", "12", "103", 0), _fill("sell", "12", "99", 4)]
    s = score_drill(PLAN, fills, bars, total_pnl=Decimal(-48))
    by = {c.key: c.status for c in s.checks}
    assert by == {"entry": "failed", "stop": "failed", "size": "failed"}
    assert (s.passed, s.applicable, s.followed_plan) == (0, 3, False)


def test_score_stop_never_reached_is_not_applicable() -> None:
    bars = _bars(["100", "101", "105"])
    fills = [_fill("buy", "5", "101", 1)]
    s = score_drill(PLAN, fills, bars, total_pnl=Decimal(20))
    by = {c.key: c.status for c in s.checks}
    assert by == {"entry": "passed", "stop": "not_applicable", "size": "passed"}
    assert (s.passed, s.applicable, s.followed_plan) == (2, 2, True)


def test_plan_rules_on_the_api(session: Session, client: TestClient) -> None:
    _seed(session, "DRLX", seed=1)
    _seed(session, "QZPM", seed=2)
    uid = _user(session)
    h = _auth(uid)
    deck = _deck(client, uid, k=2, seed=3, **{"from": "2022-02-01"}, to="2023-06-30")
    did = deck["drills"][0]["id"]
    # A long plan's stop must be below its entry.
    bad = client.put(f"/v1/drills/{did}/plan", headers=h,
                     json={"planned_entry": "10", "planned_stop": "11", "planned_size": "1"})  # fmt: skip
    assert bad.status_code == 422
    ok = client.put(f"/v1/drills/{did}/plan", headers=h,
                    json={"planned_entry": "100", "planned_stop": "90", "planned_size": "5"})  # fmt: skip
    assert ok.status_code == 200 and ok.json()["planned_risk"] == "50.000000"
    assert not ok.json()["locked"]
    assert client.get(f"/v1/drills/{did}", headers=h).json()["status"] == "in_progress"
    assert client.post(f"/v1/drills/{did}/orders", headers=h,
                       json={"side": "buy", "quantity": "5"}).status_code == 200  # fmt: skip
    locked = client.put(f"/v1/drills/{did}/plan", headers=h,
                        json={"planned_entry": "100", "planned_stop": "90", "planned_size": "6"})  # fmt: skip
    assert locked.status_code == 409
    view = client.get(f"/v1/drills/{did}", headers=h).json()
    assert view["plan"]["locked"] and view["plan"]["planned_size"] == "5.000000"
    assert view["score"] is None  # scored only after the reveal


# --- reveal ---------------------------------------------------------------------


def test_reveal_shows_everything_and_scores(session: Session, client: TestClient) -> None:
    days = _seed(session, "DRLX", seed=1)
    _seed(session, "QZPM", seed=2)
    uid = _user(session)
    h = _auth(uid)
    deck = _deck(client, uid, k=3, seed=5, **{"from": "2022-02-01"}, to="2023-06-30")
    did = deck["drills"][0]["id"]
    drill = session.get(Drill, did)
    assert drill is not None
    view = client.get(f"/v1/drills/{did}", headers=h).json()
    close = Decimal(view["bar"]["close"])
    client.put(f"/v1/drills/{did}/plan", headers=h, json={
        "planned_entry": str(close), "planned_stop": str(close - 1), "planned_size": "3"})  # fmt: skip
    client.post(f"/v1/drills/{did}/orders", headers=h, json={"side": "buy", "quantity": "3"})
    out = client.post(f"/v1/drills/{did}/reveal", headers=h)
    assert out.status_code == 200
    body = out.json()
    assert body["status"] == "revealed" and not body["anonymised"]
    assert body["label"] == drill.ticker
    reveal = body["reveal"]
    assert reveal["ticker"] == drill.ticker and reveal["name"] == NAMES[drill.ticker]
    assert reveal["trigger_date"] == drill.trigger_date.isoformat()
    shown = drill.trigger_date - timedelta(weeks=drill.date_offset_weeks)
    assert reveal["shown_trigger_date"] == shown.isoformat()
    assert [a["bars"] for a in reveal["after"]] == [5, 20, 60]
    i = days.index(drill.trigger_at)
    if i + 5 < len(days):
        assert reveal["after"][0]["date"] == days[i + 5].date().isoformat()
    assert body["session"]["status"] == "cancelled"  # ended early by the reveal
    assert body["score"]["traded"] and body["score"]["checks"][0]["status"] == "passed"
    assert body["history"][-1]["ts"][:10] in {d.date().isoformat() for d in days}
    # Revealed: the replay routes serve it now; the deck row names it.
    assert client.get(f"/v1/replay/sessions/{drill.session_id}", headers=h).status_code == 200
    rows = client.get(f"/v1/drills/decks/{deck['id']}", headers=h).json()
    row = next(r for r in rows["drills"] if r["id"] == did)
    assert row["ticker"] == drill.ticker and row["status"] == "revealed"
    assert rows["summary"]["revealed"] == 1 and rows["summary"]["traded"] == 1
    # Revealing again changes nothing; the plan is final.
    assert client.post(f"/v1/drills/{did}/reveal", headers=h).status_code == 200
    assert client.put(f"/v1/drills/{did}/plan", headers=h, json={
        "planned_entry": "2", "planned_stop": "1", "planned_size": "1"}).status_code == 409  # fmt: skip


def test_deck_without_anonymisation_names_the_symbol(session: Session, client: TestClient) -> None:
    _seed(session, "DRLX", seed=1)
    _seed(session, "QZPM", seed=2)
    uid = _user(session)
    deck = _deck(client, uid, k=2, anonymised=False, **{"from": "2022-02-01"}, to="2023-06-30")
    row = deck["drills"][0]
    assert row["ticker"] in NAMES and row["label"] == row["ticker"]
    drill = session.get(Drill, row["id"])
    assert drill is not None and drill.date_offset_weeks == 0
    view = client.get(f"/v1/drills/{row['id']}", headers=_auth(uid)).json()
    assert view["label"] == drill.ticker and view["date_note"] is None
    assert (
        client.get(f"/v1/replay/sessions/{drill.session_id}", headers=_auth(uid)).status_code == 200
    )


def test_inline_rule_is_saved_as_a_version(session: Session, client: TestClient) -> None:
    _seed(session, "DRLX", seed=1)
    _seed(session, "QZPM", seed=2)
    uid = _user(session)
    a = _deck(client, uid, k=2, **{"from": "2022-02-01"}, to="2023-06-30")
    b = _deck(client, uid, k=2, **{"from": "2022-02-01"}, to="2023-06-30")
    assert a["rule"]["setup_version_id"] == b["rule"]["setup_version_id"]
    version = session.get(SetupVersion, a["rule"]["setup_version_id"])
    assert version is not None
    setup = session.get(Setup, version.setup_id)
    assert setup is not None and setup.name == decks.INLINE_SETUP_NAME and setup.user_id == uid
    # A saved version works as the rule too.
    c = _deck(client, uid, k=2, rule={"setup_version_id": version.id},
              **{"from": "2022-02-01"}, to="2023-06-30")  # fmt: skip
    assert c["rule"]["setup_version_id"] == version.id


def test_errors(session: Session, client: TestClient) -> None:
    _seed(session, "DRLX", seed=1)
    uid = _user(session)
    h = _auth(uid)
    base = {"universe": {"tickers": ["DRLX"]}, "from": "2022-02-01", "to": "2023-06-30"}
    assert client.post("/v1/drills/decks", headers=h,
                       json={**base, "rule": {"rule": "close >"}}).status_code == 422  # fmt: skip
    assert client.post("/v1/drills/decks", headers=h,
                       json={**base, "rule": {"rule": RULE}, "k": 26}).status_code == 422  # fmt: skip
    assert client.post("/v1/drills/decks", headers=h, json={
        **base, "rule": {"rule": "close < 0"}}).status_code == 400  # fmt: skip
    assert client.post("/v1/drills/decks", headers=h, json={
        **base, "universe": {"tickers": ["NOPE"]}, "rule": {"rule": RULE}}).status_code == 404  # fmt: skip
    assert client.post("/v1/drills/decks", json={**base, "rule": {"rule": RULE}}).status_code == 401


# --- delete and isolation ---------------------------------------------------------


def test_delete_deck_removes_drills_and_sessions(session: Session, client: TestClient) -> None:
    _seed(session, "DRLX", seed=1)
    _seed(session, "QZPM", seed=2)
    uid = _user(session)
    deck = _deck(client, uid, k=3, **{"from": "2022-02-01"}, to="2023-06-30")
    sids = [d.session_id for d in session.exec(select(Drill)).all()]
    assert client.delete(f"/v1/drills/decks/{deck['id']}", headers=_auth(uid)).status_code == 204
    session.expire_all()
    assert session.get(DrillDeck, deck["id"]) is None
    assert session.exec(select(Drill)).all() == []
    assert all(session.get(ReplaySession, s) is None for s in sids)
    assert client.get(f"/v1/drills/decks/{deck['id']}", headers=_auth(uid)).status_code == 404


def test_user_isolation(session: Session, client: TestClient) -> None:
    _seed(session, "DRLX", seed=1)
    _seed(session, "QZPM", seed=2)
    owner = _user(session)
    other = _auth(_user(session, "other@stockviz.dev"))
    deck = _deck(client, owner, k=2, **{"from": "2022-02-01"}, to="2023-06-30")
    did = deck["drills"][0]["id"]
    assert client.get("/v1/drills/decks", headers=other).json() == []
    assert client.get(f"/v1/drills/decks/{deck['id']}", headers=other).status_code == 404
    assert client.delete(f"/v1/drills/decks/{deck['id']}", headers=other).status_code == 404
    for method, path, body in (
        ("get", f"/v1/drills/{did}", None),
        ("put", f"/v1/drills/{did}/plan",
         {"planned_entry": "2", "planned_stop": "1", "planned_size": "1"}),
        ("post", f"/v1/drills/{did}/orders", {"side": "buy", "quantity": "1"}),
        ("post", f"/v1/drills/{did}/advance", None),
        ("get", f"/v1/drills/{did}/events", None),
        ("get", f"/v1/drills/{did}/drawings", None),
        ("post", f"/v1/drills/{did}/reveal", None),
    ):  # fmt: skip
        kwargs = {"headers": other}
        if body is not None:
            kwargs["json"] = body
        assert getattr(client, method)(path, **kwargs).status_code == 404, path
    assert client.get(f"/v1/drills/{did}", headers=_auth(owner)).status_code == 200
    assert json.dumps(client.get("/v1/drills/decks", headers=_auth(owner)).json())
