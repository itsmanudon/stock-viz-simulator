"""A7.5 (M5.6): a thesis's kill rule is a linked rule alert, judged nightly."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlmodel import Session, col, select

from stockviz.models import Alert, Notification
from stockviz.models.alert import AlertKind
from stockviz.services.alerts.engine import evaluate_pending_alerts
from tests.symbols import seed_symbols
from tests.test_rule_alerts import _bar
from tests.test_theses_router import _auth, _user


def _alerts(session: Session) -> list[Alert]:
    session.expire_all()
    return list(session.exec(select(Alert).where(col(Alert.kind) == AlertKind.RULE)).all())


def test_kill_rule_follows_the_thesis_and_fires_once(session: Session, client: TestClient) -> None:
    seed_symbols(session, "AAPL")
    uid = _user(session, "kill@stockviz.dev")
    h = _auth(uid)
    _bar(session, 0, 90)
    made = client.post("/v1/theses", headers=h, json={
        "ticker": "AAPL", "title": "Services grow", "body": "Margins expand.",
        "kill_rule": "close < 80"})  # fmt: skip
    assert made.status_code == 201, made.text
    tid = made.json()["id"]
    assert made.json()["kill_state"] == "armed"
    (alert,) = _alerts(session)
    assert alert.params and alert.params["thesis_id"] == tid and alert.ticker == "AAPL"
    first_version = alert.setup_version_id

    # A changed rule points the same alert at a new version and re-arms it.
    patched = client.patch(f"/v1/theses/{tid}", headers=h, json={"kill_rule": "close < 85"})
    assert patched.status_code == 200
    (alert,) = _alerts(session)
    assert alert.setup_version_id != first_version and alert.triggered_at is None

    assert evaluate_pending_alerts(session) == 0  # 90: not below 85
    _bar(session, 1, 84)
    assert evaluate_pending_alerts(session) == 1  # crosses below 85
    assert evaluate_pending_alerts(session) == 0  # once
    body = client.get("/v1/theses", headers=h).json()[0]
    assert body["kill_state"] == "fired" and body["kill_fired_on"] is not None
    assert body["status"] == "open"  # a firing never closes the thesis
    notes = session.exec(select(Notification).where(col(Notification.user_id) == uid)).all()
    assert len(notes) == 1


def test_closing_pauses_and_removing_deletes(session: Session, client: TestClient) -> None:
    seed_symbols(session, "AAPL")
    uid = _user(session, "kill2@stockviz.dev")
    h = _auth(uid)
    a = client.post("/v1/theses", headers=h, json={
        "ticker": "AAPL", "title": "A", "body": "x", "kill_rule": "close < 80"}).json()  # fmt: skip
    b = client.post("/v1/theses", headers=h, json={
        "ticker": "AAPL", "title": "B", "body": "y", "kill_rule": "close < 70"}).json()  # fmt: skip
    assert len(_alerts(session)) == 2
    client.patch(f"/v1/theses/{a['id']}", headers=h, json={"kill_rule": None})
    remaining = _alerts(session)
    assert [x.params["thesis_id"] for x in remaining if x.params] == [b["id"]]
    closed = client.post(f"/v1/theses/{b['id']}/close", headers=h, json={"status": "invalidated"})
    assert closed.json()["kill_state"] == "paused"
    assert _alerts(session)[0].paused is True


def test_no_kill_rule_no_alert(session: Session, client: TestClient) -> None:
    seed_symbols(session, "AAPL")
    uid = _user(session, "kill3@stockviz.dev")
    made = client.post("/v1/theses", headers=_auth(uid), json={
        "ticker": "AAPL", "title": "A", "body": "x"}).json()  # fmt: skip
    assert made["kill_state"] == "none" and _alerts(session) == []
