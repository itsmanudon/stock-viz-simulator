"""A2.3: alerts on Rule DSL setup versions.

Same semantics as the other bar rules (RS-8): fire on the crossing from
not-true to true, arm from the bar known at ``armed_at``, ``once`` vs
``every_cross`` with a cooldown, one event per bar (unique dedupe key).
``unknown`` never fires and never counts as true.
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
    AlertEvent,
    AlertKind,
    AlertRepeat,
    Notification,
    PriceBar,
    User,
)
from stockviz.services.alerts import evaluate_pending_alerts
from stockviz.services.dsl import compile_rule
from stockviz.services.setups import store
from stockviz.services.setups.presets import seed_presets
from stockviz.settings import get_settings
from tests.symbols import seed_symbols

DAY0 = datetime(2025, 1, 6)  # a Monday
SECRET = get_settings().internal_api_token


def _auth(user_id: int) -> dict[str, str]:
    return {
        "Authorization": "Bearer "
        + jose_jwt.encode({"sub": str(user_id)}, SECRET, algorithm="HS256")
    }


def _user(session: Session, email: str = "rule@stockviz.dev") -> int:
    user = User(email=email, name=email.split("@")[0])
    session.add(user)
    session.commit()
    assert user.id is not None
    return user.id


def _day(n: int) -> datetime:
    """The n-th weekday after DAY0 (bars on sessions only)."""
    day, left = DAY0, n
    while left:
        day += timedelta(days=1)
        if day.weekday() < 5:
            left -= 1
    return day


def _bar(session: Session, n: int, close: float, ticker: str = "AAPL") -> None:
    c = Decimal(str(close))
    session.add(
        PriceBar(
            ticker=ticker, ts=_day(n), interval="1d",
            open=c, high=c, low=c, close=c, volume=1000, source="test",
        )
    )  # fmt: skip
    session.commit()


def _setup(session: Session, user_id: int, rule: str, name: str = "Over 100") -> int:
    _setup_row, version = store.create_setup(
        session, user_id, name=name, kind="alert", rule=compile_rule(rule)
    )
    assert version.id is not None
    return version.id


def _rule_alert(
    session: Session,
    user_id: int,
    version_id: int,
    *,
    repeat: AlertRepeat = AlertRepeat.ONCE,
    cooldown: int = 1,
    armed_at: datetime | None = None,
) -> Alert:
    alert = Alert(
        user_id=user_id,
        ticker="AAPL",
        kind=AlertKind.RULE,
        setup_version_id=version_id,
        params={"setup_name": "Over 100", "version": 1, "canonical": "close > 100"},
        repeat=repeat,
        cooldown_sessions=cooldown,
        armed_at=armed_at,
    )
    session.add(alert)
    session.commit()
    return alert


def _events(session: Session) -> list[AlertEvent]:
    return list(session.exec(select(AlertEvent).order_by(AlertEvent.id)).all())  # type: ignore[arg-type]


def test_a_rule_alert_fires_on_the_crossing_once(session: Session) -> None:
    seed_symbols(session, "AAPL")
    user = _user(session)
    version = _setup(session, user, "close > 100")
    _bar(session, 0, 90)
    alert = _rule_alert(session, user, version)

    assert evaluate_pending_alerts(session) == 0  # 90: not true
    _bar(session, 1, 105)
    assert evaluate_pending_alerts(session) == 1  # crosses
    assert evaluate_pending_alerts(session) == 0  # the same bar again: nothing
    (event,) = _events(session)
    assert event.bar_date == _day(1).date()
    assert event.dedupe_key == f"{alert.id}:{_day(1).date().isoformat()}"
    assert "Over 100" in event.message and "close > 100" in event.message
    note = session.exec(select(Notification)).one()
    assert note.category == "alert" and note.data and note.data["kind"] == "rule"

    _bar(session, 2, 90)
    _bar(session, 3, 110)
    assert evaluate_pending_alerts(session) == 0  # once: stopped after firing


def test_a_rerun_of_the_same_bar_writes_nothing_twice(session: Session) -> None:
    seed_symbols(session, "AAPL")
    user = _user(session)
    version = _setup(session, user, "close > 100")
    _bar(session, 0, 90)
    alert = _rule_alert(session, user, version, repeat=AlertRepeat.EVERY_CROSS)
    evaluate_pending_alerts(session)
    _bar(session, 1, 105)
    assert evaluate_pending_alerts(session) == 1
    # Forget the evaluation state, as a crashed run might: the dedupe key holds.
    alert.last_bar_date = _day(0).date()
    alert.last_state = False
    session.add(alert)
    session.commit()
    assert evaluate_pending_alerts(session) == 0
    assert len(_events(session)) == 1


def test_every_cross_waits_for_the_cooldown(session: Session) -> None:
    seed_symbols(session, "AAPL")
    user = _user(session)
    version = _setup(session, user, "close > 100")
    _bar(session, 0, 90)
    _rule_alert(session, user, version, repeat=AlertRepeat.EVERY_CROSS, cooldown=3)
    evaluate_pending_alerts(session)

    fired = []
    for n, close in enumerate([105, 95, 105, 95, 95, 105], start=1):
        _bar(session, n, close)
        fired.append(evaluate_pending_alerts(session))
    # Fires on bar 1; the cross on bar 3 is 2 bars later (< 3); bar 6 is 5 later.
    assert fired == [1, 0, 0, 0, 0, 1]


def test_unknown_never_fires_and_never_counts_as_true(session: Session) -> None:
    seed_symbols(session, "AAPL")
    user = _user(session)
    # sma(close, 3) is unknown until three bars exist.
    version = _setup(session, user, "close > sma(close, 3)")
    _bar(session, 0, 100)
    alert = _rule_alert(session, user, version, repeat=AlertRepeat.EVERY_CROSS)
    assert evaluate_pending_alerts(session) == 0
    _bar(session, 1, 120)  # would be "true" if a 2-bar mean counted: still unknown
    assert evaluate_pending_alerts(session) == 0
    session.refresh(alert)
    assert alert.last_state is False  # unknown is recorded as not true
    _bar(session, 2, 130)  # first known value: 130 > 116.67, true after unknown
    assert evaluate_pending_alerts(session) == 1


def test_a_rule_that_is_always_unknown_never_fires(session: Session) -> None:
    seed_symbols(session, "AAPL")
    user = _user(session)
    version = _setup(session, user, "fundamental.pe < 1000 or close < 0")
    _rule_alert(session, user, version, repeat=AlertRepeat.EVERY_CROSS)
    for n in range(5):
        _bar(session, n, 100 + n)
        assert evaluate_pending_alerts(session) == 0
    assert _events(session) == []


@pytest.mark.placement_guard
def test_a_rule_already_true_when_armed_waits_for_the_next_cross(session: Session) -> None:
    seed_symbols(session, "AAPL")
    user = _user(session)
    version = _setup(session, user, "close > 100")
    _bar(session, 0, 105)
    _bar(session, 1, 106)
    # Armed late on day 2 (UTC): the newest close known then is day 1's (true).
    _rule_alert(session, user, version, armed_at=_day(2) + timedelta(hours=10))
    _bar(session, 2, 107)  # still true: no crossing since arming
    assert evaluate_pending_alerts(session) == 0
    _bar(session, 3, 95)
    assert evaluate_pending_alerts(session) == 0
    _bar(session, 4, 101)  # the next cross
    assert evaluate_pending_alerts(session) == 1


# --- API -------------------------------------------------------------------


def test_create_a_rule_alert_from_your_setup(session: Session, client: TestClient) -> None:
    seed_symbols(session, "AAPL")
    user = _user(session)
    version = _setup(session, user, "close>100  # comment")
    body = client.post(
        "/v1/alerts",
        headers=_auth(user),
        json={"ticker": "aapl", "kind": "rule", "setup_version_id": version, "repeat": "once"},
    )
    assert body.status_code == 201, body.text
    out = body.json()
    assert out["kind"] == "rule" and out["setup_version_id"] == version
    assert out["params"]["canonical"] == "close > 100"
    assert out["params"]["setup_name"] == "Over 100"
    assert out["description"] == "AAPL: Over 100 v1 becomes true (close > 100)"
    listed = client.get("/v1/alerts", headers=_auth(user)).json()
    assert [a["kind"] for a in listed] == ["rule"]


def test_rule_alert_validation(session: Session, client: TestClient) -> None:
    seed_symbols(session, "AAPL")
    me = _user(session)
    other = _user(session, "other@stockviz.dev")
    mine = _setup(session, me, "close > 100")
    theirs = _setup(session, other, "close > 50", name="Theirs")
    h = _auth(me)

    def post(body: dict) -> int:
        return client.post("/v1/alerts", headers=h, json=body).status_code

    assert post({"ticker": "AAPL", "kind": "rule"}) == 400  # no version
    assert post({"kind": "rule", "setup_version_id": mine}) == 400  # no ticker
    assert post({"ticker": "AAPL", "kind": "rule", "setup_version_id": theirs}) == 404
    assert post({"ticker": "AAPL", "kind": "rule", "setup_version_id": 99999}) == 404
    assert (
        post(
            {"ticker": "AAPL", "direction": "above", "target_price": "1", "setup_version_id": mine}
        )
        == 400
    )
    setup = store.get_owned(session, store.visible_version(session, mine, me).setup_id, me)
    store.archive(session, setup)
    assert post({"ticker": "AAPL", "kind": "rule", "setup_version_id": mine}) == 409


def test_a_preset_can_drive_a_rule_alert(session: Session, client: TestClient) -> None:
    seed_symbols(session, "AAPL")
    seed_presets(session)
    me = _user(session)
    presets = client.get("/v1/setups/presets").json()
    version_id = presets[0]["latest_version"]["id"]
    r = client.post(
        "/v1/alerts",
        headers=_auth(me),
        json={"ticker": "AAPL", "kind": "rule", "setup_version_id": version_id},
    )
    assert r.status_code == 201, r.text
    assert r.json()["params"]["preset"] is True


def test_patch_points_a_rule_alert_at_another_version_and_rearms(
    session: Session, client: TestClient
) -> None:
    seed_symbols(session, "AAPL")
    me = _user(session)
    v1 = _setup(session, me, "close > 100")
    v2 = _setup(session, me, "close > 200", name="Over 200")
    created = client.post(
        "/v1/alerts",
        headers=_auth(me),
        json={"ticker": "AAPL", "kind": "rule", "setup_version_id": v1},
    ).json()
    alert = session.get(Alert, created["id"])
    assert alert is not None
    alert.last_state = True
    session.add(alert)
    session.commit()
    r = client.patch(
        f"/v1/alerts/{created['id']}", headers=_auth(me), json={"setup_version_id": v2}
    )
    assert r.status_code == 200, r.text
    assert r.json()["setup_version_id"] == v2
    assert r.json()["params"]["setup_name"] == "Over 200"
    assert r.json()["last_state"] is None  # re-armed
    # A price alert cannot take a setup version.
    price = client.post(
        "/v1/alerts",
        headers=_auth(me),
        json={"ticker": "AAPL", "direction": "above", "target_price": "1"},
    ).json()
    assert (
        client.patch(
            f"/v1/alerts/{price['id']}", headers=_auth(me), json={"setup_version_id": v2}
        ).status_code
        == 400
    )
    # Pausing still works with the optional body.
    paused = client.patch(f"/v1/alerts/{price['id']}", headers=_auth(me), json={"paused": True})
    assert paused.json()["paused"] is True
