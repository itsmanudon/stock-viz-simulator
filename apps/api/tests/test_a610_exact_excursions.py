"""A6.10: exact MAE and MFE from stored minutes (worked by hand)."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlmodel import Session, col, select

from stockviz.models import IntradayBar, Trade
from stockviz.services.instruments import resolve_symbol
from stockviz.services.journal.roundtrips import (
    LedgerFill,
    MinuteBar,
    RoundTrip,
    minute_excursions,
)
from tests.test_journal_entries import _aapl, _bar, _entries, _h, _trade, _user

D = Decimal
DAY = date(2026, 1, 6)


def _fill(side: str, qty: str, price: str, hhmm_ss: str) -> LedgerFill:
    h, m, s = (int(x) for x in hhmm_ss.split(":"))
    return LedgerFill(key=f"{side}{hhmm_ss}", side=side, quantity=D(qty), price=D(price),
                      fees=D(0), at=datetime(2026, 1, 6, h, m, s), venue_date=DAY)  # fmt: skip


def _minute(hhmm: str, low: str, high: str) -> MinuteBar:
    h, m = (int(x) for x in hhmm.split(":"))
    return MinuteBar(at=datetime(2026, 1, 6, h, m), day=DAY, high=D(high), low=D(low))


MINUTES = [
    _minute("15:00", "99", "101"),  # entry minute: the buy at 100 counts from its price
    _minute("15:01", "97", "100.5"),  # held: low 97 -> MAE -3
    _minute("15:02", "99", "104"),  # held: high 104 -> MFE +4
    _minute("15:03", "102", "108"),  # exit minute: shares sold at 103 count from that price
]


def test_long_entry_exact_to_the_minute() -> None:
    trip = RoundTrip(fills=[_fill("buy", "10", "100", "15:00:20"),
                            _fill("sell", "10", "103", "15:03:10")], closed=True)  # fmt: skip
    result = minute_excursions(trip, MINUTES, initial_risk=D("20"))
    assert result.basis == "exact_minutes" and result.mae and result.mfe
    # The shares held at 15:03's open saw its whole range (108), even though
    # they were sold inside that minute: exact to the minute, not the second.
    assert result.mae.per_share == D("-3") and result.mae.price == D("97")
    assert result.mfe.per_share == D("8") and result.mfe.price == D("108")
    assert result.mae.amount == D("-30") and result.mae.r == -1.5


def test_short_entry_mirrors() -> None:
    trip = RoundTrip(fills=[_fill("sell", "5", "100", "15:00:05"),
                            _fill("buy", "5", "98", "15:02:30")], closed=True, side="short")  # fmt: skip
    result = minute_excursions(trip, MINUTES[:3])
    assert result.mae and result.mfe
    assert result.mae.per_share == D("-4")  # high 104 in 15:02 while short from 100
    assert result.mfe.per_share == D("3")  # low 97 in 15:01


def test_no_minutes_is_unknown() -> None:
    trip = RoundTrip(fills=[_fill("buy", "1", "100", "15:00:00"),
                            _fill("sell", "1", "101", "15:01:00")], closed=True)  # fmt: skip
    result = minute_excursions(trip, [])
    assert result.mae is None and result.reason


# --- the trade replay route ---------------------------------------------------------


def _paper_trip(
    session: Session, client: TestClient, *, plan: dict | None = None
) -> tuple[int, int]:
    _aapl(session)
    uid = _user(session)
    extra = {"plan": plan} if plan else {}
    _trade(client, uid, "buy", "10", **extra)
    _trade(client, uid, "sell", "10")
    buy, sell = session.exec(select(Trade).order_by(col(Trade.id))).all()
    buy.ts = datetime(2025, 4, 10, 18, 2, 20)
    sell.ts = datetime(2025, 4, 10, 18, 5, 10)
    session.add_all([buy, sell])
    session.commit()
    entry = _entries(client, uid, "?status=closed")["entries"][0]
    return uid, entry["id"]


def _minutes(session: Session, rows: list[tuple[str, str]]) -> None:
    instrument = resolve_symbol(session, "AAPL")
    assert instrument is not None and instrument.id is not None
    for minute, (low, high) in enumerate(rows):
        ts = datetime(2025, 4, 10, 18, minute)
        session.add(IntradayBar(instrument_id=instrument.id, feed="iex", interval="1m", ts=ts,
                                open=D(low), high=D(high), low=D(low), close=D(high), volume=10,
                                source="alpaca_iex", available_at=ts + timedelta(minutes=1)))  # fmt: skip
    session.commit()


PLAN = {"planned_entry": "148", "planned_stop": "145", "planned_size": "10"}


def test_trade_replay_on_minutes_with_the_hesitation_strip(
    session: Session, client: TestClient
) -> None:
    uid, entry_id = _paper_trip(session, client, plan=PLAN)
    # 18:00 touches 148 (the plan's entry); the fill is at 18:02, two bars
    # later. 18:04 trades through the stop 145; the exit is at 18:05.
    _minutes(session, [("147", "149"), ("149", "151"), ("149", "151"), ("148", "150"),
                       ("144", "149"), ("146", "148")])  # fmt: skip
    response = client.get(f"/v1/journal/entries/{entry_id}/replay", headers=_h(uid))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["interval"] == "1m" and body["bars_note"] == "Minute bars."
    assert len(body["bars"]) == 6 and [f["side"] for f in body["fills"]] == ["buy", "sell"]
    assert body["planned_stop"] == "145.000000" and body["excursions"]["basis"] == "exact_minutes"
    h = body["hesitation"]
    assert h["entry_touched_at"].startswith("2025-04-10T18:00") and h["wait_bars"] == 2
    assert h["stop_breached_at"].startswith("2025-04-10T18:04")
    assert h["stop_honoured"] is False  # held one more bar past the breach


def test_trade_replay_falls_back_to_daily_bars(session: Session, client: TestClient) -> None:
    uid, entry_id = _paper_trip(session, client)
    _bar(session, "AAPL", date(2025, 4, 11), "150", "152", "149", "151")
    body = client.get(f"/v1/journal/entries/{entry_id}/replay", headers=_h(uid)).json()
    assert body["interval"] == "1d" and body["bars_note"] == "Daily bars, approximate."
    assert body["hesitation"] is None  # no plan
    assert body["excursions"]["basis"] == "approximate_daily"


def test_trade_replay_is_per_user(session: Session, client: TestClient) -> None:
    _uid, entry_id = _paper_trip(session, client)
    other = _user(session)
    assert (
        client.get(f"/v1/journal/entries/{entry_id}/replay", headers=_h(other)).status_code == 404
    )
