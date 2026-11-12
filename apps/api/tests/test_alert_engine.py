"""Alert rules (Phase 7.1): crossings, history, deduplication, re-arming.

Audit RS-8: an alert fired at once if its condition was already met, kept no
trigger price or bar date, and could not be re-armed.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from jose import jwt as jose_jwt
from sqlmodel import Session, select

from stockviz.models import (
    Alert,
    AlertDirection,
    AlertEvent,
    AlertKind,
    AlertRepeat,
    PriceBar,
    User,
)
from stockviz.services.alerts import evaluate_pending_alerts
from stockviz.settings import get_settings
from tests.symbols import seed_symbols

DAY0 = datetime(2025, 1, 6)  # a Monday


def _user(session: Session) -> int:
    user = User(email="rules@stockviz.dev", name="Rules")
    session.add(user)
    session.commit()
    assert user.id is not None
    return user.id


def _bar(session: Session, day: int, close: float, ticker: str = "AAPL") -> None:
    c = Decimal(str(close))
    session.add(
        PriceBar(
            ticker=ticker, ts=DAY0 + timedelta(days=day), interval="1d",
            open=c, high=c, low=c, close=c, volume=1000, source="test",
        )
    )  # fmt: skip
    session.commit()


def _events(session: Session) -> list[AlertEvent]:
    return list(session.exec(select(AlertEvent).order_by(AlertEvent.id)).all())  # type: ignore[arg-type]


@pytest.mark.placement_guard
def test_an_alert_already_met_waits_for_the_next_cross(session: Session) -> None:
    seed_symbols(session, "AAPL")
    user = _user(session)
    _bar(session, 0, 90)
    _bar(session, 1, 95)
    # Armed on day 2 at 10:00 UTC: the newest close it could see is day 1's.
    alert = Alert(
        user_id=user, ticker="AAPL", direction=AlertDirection.BELOW,
        target_price=Decimal(100), armed_at=DAY0 + timedelta(days=2, hours=10),
    )  # fmt: skip
    session.add(alert)
    session.commit()

    _bar(session, 2, 96)  # still below: already met when armed, so nothing
    assert evaluate_pending_alerts(session) == 0
    _bar(session, 3, 105)  # above
    assert evaluate_pending_alerts(session) == 0
    _bar(session, 4, 99)  # crosses below
    assert evaluate_pending_alerts(session) == 1
    assert evaluate_pending_alerts(session) == 0  # the same bar twice: nothing

    (event,) = _events(session)
    assert event.bar_date == (DAY0 + timedelta(days=4)).date()
    assert event.observed == Decimal(99) and event.threshold == Decimal(100)
    assert "closed at 99.00" in event.message
    session.refresh(alert)
    assert alert.triggered_at is not None and alert.last_fired_bar_date == event.bar_date

    _bar(session, 5, 105)
    _bar(session, 6, 98)
    assert evaluate_pending_alerts(session) == 0  # a once rule stops after firing


def test_rsi_crossing_below_30_fires_once_with_its_value(session: Session) -> None:
    seed_symbols(session, "AAPL")
    user = _user(session)
    closes = [100 + i for i in range(40)] + [140 - 6 * i for i in range(1, 8)]
    for day, close in enumerate(closes[:-3]):
        _bar(session, day, close)
    rule = Alert(
        user_id=user, ticker="AAPL", kind=AlertKind.TECHNICAL,
        params={"indicator": "rsi_14", "op": "below", "value": 30.0},
    )  # fmt: skip
    session.add(rule)
    session.commit()

    fired = 0
    for day in range(len(closes) - 3, len(closes)):
        _bar(session, day, closes[day])
        fired += evaluate_pending_alerts(session)
    assert fired == 1  # crossed once, then stayed below
    (event,) = _events(session)
    assert event.observed is not None and event.observed < 30
    assert event.threshold == Decimal(30)
    assert "RSI 14 crosses below 30" in event.message


def test_every_cross_rearms_after_its_cooldown(session: Session) -> None:
    seed_symbols(session, "AAPL")
    user = _user(session)
    _bar(session, 0, 95)
    rule = Alert(
        user_id=user, ticker="AAPL", direction=AlertDirection.ABOVE, target_price=Decimal(100),
        repeat=AlertRepeat.EVERY_CROSS, cooldown_sessions=3,
    )  # fmt: skip
    session.add(rule)
    session.commit()
    assert evaluate_pending_alerts(session) == 0  # arms below the level
    fired = []
    for day, close in enumerate([101, 99, 102, 98, 97, 103], start=1):
        _bar(session, day, close)
        fired.append(evaluate_pending_alerts(session))
    # Day 1 crosses; day 3 crosses again but only 2 bars later (cooldown 3);
    # day 6 crosses 5 bars after the first firing.
    assert fired == [1, 0, 0, 0, 0, 1]


def test_a_session_move_rule_fires_on_each_big_move(session: Session) -> None:
    seed_symbols(session, "AAPL")
    user = _user(session)
    _bar(session, 0, 100)
    rule = Alert(
        user_id=user, ticker="AAPL", params={"move_pct": 5.0}, repeat=AlertRepeat.EVERY_CROSS,
    )  # fmt: skip
    session.add(rule)
    session.commit()
    fired = []
    for day, close in enumerate([106, 100, 101, 95], start=1):
        _bar(session, day, close)
        fired.append(evaluate_pending_alerts(session))
    assert fired == [1, 1, 0, 1]  # +6%, -5.7%, +1%, -5.9%


def test_close_crossing_above_its_moving_average(session: Session) -> None:
    seed_symbols(session, "AAPL")
    user = _user(session)
    for day, close in enumerate([10, 10, 10, 9, 8]):
        _bar(session, day, close)
    rule = Alert(
        user_id=user, ticker="AAPL", kind=AlertKind.TECHNICAL,
        params={"indicator": "close", "op": "above", "compare_to": "sma_3"},
    )  # fmt: skip
    session.add(rule)
    session.commit()
    assert evaluate_pending_alerts(session) == 0  # close 8 under SMA 9
    _bar(session, 5, 12)  # SMA(9, 8, 12) = 9.67, close 12 above
    assert evaluate_pending_alerts(session) == 1


def _headers(user_id: int) -> dict[str, str]:
    token = jose_jwt.encode({"sub": str(user_id)}, get_settings().internal_api_token, "HS256")
    return {"Authorization": f"Bearer {token}"}


def test_rules_through_the_api(session: Session, client: TestClient) -> None:
    seed_symbols(session, "AAPL")
    user = _user(session)
    h = _headers(user)
    for day, close in enumerate([100, 101, 102]):
        _bar(session, day, close)

    bad = [
        {"ticker": "AAPL", "kind": "technical", "params": {"indicator": "nope_3", "op": "above", "value": 1}},
        {"ticker": "AAPL", "kind": "technical", "params": {"indicator": "rsi_14", "op": "above"}},
        {"ticker": "AAPL", "kind": "technical", "params": {"indicator": "macd", "op": "above", "value": 0}},
        {"ticker": "AAPL", "kind": "price"},
    ]  # fmt: skip
    for body in bad:
        assert client.post("/v1/alerts", json=body, headers=h).status_code == 400, body

    made = client.post(
        "/v1/alerts",
        json={"ticker": "AAPL", "kind": "technical",
              "params": {"indicator": "macd.macd", "op": "above", "compare_to": "macd.signal"}},
        headers=h,
    )  # fmt: skip
    assert made.status_code == 201, made.text
    body = made.json()
    assert body["kind"] == "technical" and body["armed_at"] is not None
    assert "MACD" in body["description"] and "crosses above" in body["description"]

    level = client.post(
        "/v1/alerts",
        json={"ticker": "AAPL", "direction": "above", "target_price": "101.5"},
        headers=h,
    ).json()
    assert level["description"] == "AAPL closes above 101.50"
    evaluate_pending_alerts(session)
    history = client.get("/v1/alerts/events", headers=h).json()
    assert [e["alert_id"] for e in history] == [level["id"]]
    assert client.get(f"/v1/alerts/{level['id']}/events", headers=h).json()[0]["bar_date"]

    rearmed = client.post(f"/v1/alerts/{level['id']}/rearm", headers=h).json()
    assert rearmed["triggered_at"] is None and rearmed["last_state"] is None
    paused = client.patch(f"/v1/alerts/{level['id']}", json={"paused": True}, headers=h).json()
    assert paused["paused"] is True
    bad_news = {"ticker": "AAPL", "kind": "news", "params": {"sentiment": "angry"}}
    assert client.post("/v1/alerts", json=bad_news, headers=h).status_code == 400
