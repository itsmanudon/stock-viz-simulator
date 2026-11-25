"""A2.3: delivery beyond the bell (signed webhook, email, Telegram).

Every transport is stubbed: ``transport.http_client`` returns an
``httpx.MockTransport`` client, ``transport.resolve`` a fixed address list,
``transport.email_sender`` a recorder. Nothing reaches the network.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from datetime import datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient
from jose import jwt as jose_jwt
from sqlmodel import Session, select

from stockviz import cli
from stockviz.models import (
    DeliveryAttempt,
    Notification,
    NotificationCategory,
    NotificationChannel,
    User,
)
from stockviz.services import delivery
from stockviz.services.delivery import transport
from stockviz.services.notifications import notify
from stockviz.settings import get_settings

SECRET = "whsec-0123456789abcdef"
HOOK = "https://hooks.example.com/stockviz"
PUBLIC_IP = "93.184.216.34"
NOW = datetime(2026, 11, 25, 22, 30)
API_SECRET = get_settings().internal_api_token


def _auth(user_id: int) -> dict[str, str]:
    return {
        "Authorization": "Bearer "
        + jose_jwt.encode({"sub": str(user_id)}, API_SECRET, algorithm="HS256")
    }


@pytest.fixture
def user(session: Session) -> User:
    row = User(email="hooks@stockviz.dev", name="Hooks")
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


class Wire:
    """Records requests; answers with ``status`` (or raises ``error``)."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.status = 200
        self.headers: dict[str, str] = {}
        self.error: Exception | None = None

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return httpx.Response(self.status, headers=self.headers, text="ok")


@pytest.fixture
def wire(monkeypatch) -> Wire:
    w = Wire()
    monkeypatch.setattr(
        transport,
        "http_client",
        lambda: httpx.Client(transport=httpx.MockTransport(w.handler), follow_redirects=False),
    )
    monkeypatch.setattr(transport, "resolve", lambda _host, _port: [PUBLIC_IP])
    return w


def _webhook(session: Session, user: User, *, muted: list[str] | None = None) -> None:
    session.add(
        NotificationChannel(
            user_id=user.id,  # type: ignore[arg-type]
            channel="webhook",
            enabled=True,
            config={"url": HOOK},
            secret=SECRET,
            muted_categories=muted or [],
        )
    )
    session.commit()


def _notify(session: Session, user: User, key: str = "k1", category=NotificationCategory.ALERT):
    row = notify(
        session,
        user_id=user.id,  # type: ignore[arg-type]
        category=category,
        title="AAPL closes above 200",
        body="AAPL closed at 201.00",
        source_key=key,
        data={"alert_id": 7},
    )
    session.commit()
    return row


def _attempts(session: Session) -> list[DeliveryAttempt]:
    return list(session.exec(select(DeliveryAttempt).order_by(DeliveryAttempt.id)).all())  # type: ignore[arg-type]


# --- staging (the outbox) ------------------------------------------------------


def test_a_notification_stages_one_send_per_enabled_channel(session: Session, user: User) -> None:
    _webhook(session, user)
    _notify(session, user)
    _notify(session, user)  # same source key: no notification, nothing staged
    (row,) = _attempts(session)
    assert row.channel == "webhook" and row.status == "pending" and row.attempts == 0
    note = session.exec(select(Notification)).one()
    assert row.notification_id == note.id
    # deliver() again is idempotent per (notification, channel).
    assert delivery.deliver(session, note) == []


def test_muted_categories_and_disabled_channels_stage_nothing(session: Session, user: User) -> None:
    _webhook(session, user, muted=["alert"])
    _notify(session, user)
    assert _attempts(session) == []
    _notify(session, user, "k2", NotificationCategory.SCREEN)
    assert len(_attempts(session)) == 1
    chan = session.exec(select(NotificationChannel)).one()
    chan.enabled = False
    session.add(chan)
    session.commit()
    _notify(session, user, "k3", NotificationCategory.SCREEN)
    assert len(_attempts(session)) == 1


def test_channels_the_server_cannot_send_stage_nothing(session: Session, user: User) -> None:
    session.add(NotificationChannel(user_id=user.id, channel="telegram", enabled=True,  # type: ignore[arg-type]
                                    config={"chat_id": "12345"}))  # fmt: skip
    session.add(NotificationChannel(user_id=user.id, channel="email", enabled=True))  # type: ignore[arg-type]
    session.commit()
    _notify(session, user)
    assert _attempts(session) == []


# --- the webhook -------------------------------------------------------------


def test_the_webhook_is_signed_and_pinned(session: Session, user: User, wire: Wire) -> None:
    _webhook(session, user)
    note = _notify(session, user)
    result = delivery.drain(session, now=NOW + timedelta(days=30))
    assert result.sent == 1
    (request,) = wire.requests
    assert request.url.host == PUBLIC_IP  # sent to the address that was checked
    assert request.headers["host"] == "hooks.example.com"
    assert request.extensions.get("sni_hostname") == "hooks.example.com"
    body = request.content
    expected = "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    assert request.headers["x-stockviz-signature"] == expected
    assert request.headers["x-stockviz-timestamp"].isdigit()
    payload = json.loads(body)
    assert payload == {
        "id": note.id,
        "category": "alert",
        "title": "AAPL closes above 200",
        "body": "AAPL closed at 201.00",
        "created_at": note.created_at.isoformat(),
        "data": {"alert_id": 7},
    }
    (row,) = _attempts(session)
    assert row.status == "sent" and row.attempts == 1 and row.sent_at is not None
    # A second drain sends nothing.
    assert delivery.drain(session, now=NOW + timedelta(days=30)).sent == 0
    assert len(wire.requests) == 1


@pytest.mark.parametrize(
    "addresses",
    [
        ["10.0.0.5"],
        ["192.168.1.1"],
        ["127.0.0.1"],
        ["169.254.169.254"],  # cloud metadata
        ["100.64.0.1"],  # carrier-grade NAT
        ["::ffff:10.0.0.1"],  # IPv4-mapped private
        ["fe80::1"],
        [PUBLIC_IP, "10.0.0.5"],  # one private answer is enough to refuse
    ],
)
def test_private_addresses_are_refused(
    session: Session, user: User, wire: Wire, monkeypatch, addresses: list[str]
) -> None:
    monkeypatch.setattr(transport, "resolve", lambda _h, _p: addresses)
    _webhook(session, user)
    _notify(session, user)
    result = delivery.drain(session, now=NOW + timedelta(days=30))
    assert result.dead == 1 and wire.requests == []
    (row,) = _attempts(session)
    assert row.status == "dead" and "private address" in (row.last_error or "")


def test_redirects_are_not_followed(session: Session, user: User, wire: Wire) -> None:
    wire.status = 302
    wire.headers = {"location": "http://169.254.169.254/latest/meta-data"}
    _webhook(session, user)
    _notify(session, user)
    assert delivery.drain(session, now=NOW + timedelta(days=30)).dead == 1
    assert len(wire.requests) == 1  # the redirect target was never requested
    (row,) = _attempts(session)
    assert "redirects are not followed" in (row.last_error or "")


def test_retry_backoff_then_dead_after_max_attempts(
    session: Session, user: User, wire: Wire, caplog
) -> None:
    wire.status = 503
    _webhook(session, user)
    _notify(session, user)
    start = NOW + timedelta(days=30)
    with caplog.at_level(logging.WARNING):
        assert delivery.drain(session, now=start).retrying == 1
        (row,) = _attempts(session)
        assert row.next_attempt_at == start + timedelta(seconds=60)
        # Not due yet: nothing is sent.
        assert delivery.drain(session, now=start + timedelta(seconds=30)).retrying == 0
        assert len(wire.requests) == 1
        when = start
        for wait in delivery.BACKOFF_SECONDS:
            when += timedelta(seconds=wait)
            delivery.drain(session, now=when)
    session.refresh(row)
    assert row.attempts == delivery.MAX_ATTEMPTS == len(wire.requests)
    assert row.status == "dead" and row.dead_at is not None
    assert row.last_error == "the webhook answered HTTP 503"
    assert SECRET not in caplog.text


def test_a_timeout_retries(session: Session, user: User, wire: Wire) -> None:
    wire.error = httpx.ReadTimeout("slow")
    _webhook(session, user)
    _notify(session, user)
    assert delivery.drain(session, now=NOW + timedelta(days=30)).retrying == 1
    (row,) = _attempts(session)
    assert row.last_error == "the webhook timed out"


def test_a_client_error_is_permanent(session: Session, user: User, wire: Wire) -> None:
    wire.status = 404
    _webhook(session, user)
    _notify(session, user)
    assert delivery.drain(session, now=NOW + timedelta(days=30)).dead == 1


def test_a_channel_turned_off_before_its_turn_is_skipped(
    session: Session, user: User, wire: Wire
) -> None:
    _webhook(session, user)
    _notify(session, user)
    chan = session.exec(select(NotificationChannel)).one()
    chan.enabled = False
    session.add(chan)
    session.commit()
    assert delivery.drain(session, now=NOW + timedelta(days=30)).skipped == 1
    assert wire.requests == []


def test_localhost_only_outside_production(session: Session, user: User, wire, monkeypatch) -> None:
    monkeypatch.setattr(transport, "resolve", lambda _h, _p: ["127.0.0.1"])
    session.add(
        NotificationChannel(
            user_id=user.id,  # type: ignore[arg-type]
            channel="webhook",
            enabled=True,
            config={"url": "http://localhost:9000/hook"},
            secret=SECRET,
        )
    )
    session.commit()
    _notify(session, user)
    assert delivery.drain(session, now=NOW + timedelta(days=30)).sent == 1
    assert wire.requests[0].url.host == "127.0.0.1"
    monkeypatch.setattr(get_settings(), "environment", "production")
    _notify(session, user, "k2")
    assert delivery.drain(session, now=NOW + timedelta(days=30)).dead == 1


# --- email and Telegram ------------------------------------------------------


class Mailbox:
    def __init__(self) -> None:
        self.sent: list[dict[str, str]] = []

    def send(self, *, to: str, subject: str, body: str) -> None:
        self.sent.append({"to": to, "subject": subject, "body": body})


def _smtp_on(monkeypatch) -> Mailbox:
    s = get_settings()
    for name, value in (
        ("smtp_host", "smtp.example.com"),
        ("smtp_port", "587"),
        ("smtp_user", "stockviz"),
        ("smtp_from", "alerts@example.com"),
    ):
        monkeypatch.setattr(s, name, value)
    from pydantic import SecretStr

    monkeypatch.setattr(s, "smtp_password", SecretStr("pw"))
    box = Mailbox()
    monkeypatch.setattr(transport, "email_sender", lambda: box)
    return box


def test_email_is_off_until_every_smtp_value_is_set(monkeypatch) -> None:
    s = get_settings()
    assert not s.email_configured and not delivery.server_available("email")
    monkeypatch.setattr(s, "smtp_host", "smtp.example.com")
    assert not s.email_configured  # one value is not enough
    assert cli.main(["deliver-notifications", "--channel", "email"]) == 2


def test_email_goes_to_the_account_address_by_default(
    session: Session, user: User, monkeypatch
) -> None:
    box = _smtp_on(monkeypatch)
    session.add(NotificationChannel(user_id=user.id, channel="email", enabled=True))  # type: ignore[arg-type]
    session.commit()
    _notify(session, user)
    assert delivery.drain(session, now=NOW + timedelta(days=30)).sent == 1
    (mail,) = box.sent
    assert mail["to"] == "hooks@stockviz.dev"
    assert mail["subject"] == "StockViz: AAPL closes above 200"
    assert "AAPL closed at 201.00" in mail["body"]


def test_telegram_sends_to_the_chat_and_never_logs_the_token(
    session: Session, user: User, wire: Wire, monkeypatch, caplog
) -> None:
    from pydantic import SecretStr

    token = "123456:telegram-secret-token"
    monkeypatch.setattr(get_settings(), "telegram_bot_token", SecretStr(token))
    session.add(NotificationChannel(user_id=user.id, channel="telegram", enabled=True,  # type: ignore[arg-type]
                                    config={"chat_id": "424242"}))  # fmt: skip
    session.commit()
    _notify(session, user)
    assert delivery.drain(session, now=NOW + timedelta(days=30)).sent == 1
    (request,) = wire.requests
    assert request.url.path == f"/bot{token}/sendMessage"
    assert json.loads(request.content)["chat_id"] == "424242"

    wire.error = httpx.ConnectError(f"cannot reach https://api.telegram.org/bot{token}/x")
    _notify(session, user, "k2")
    with caplog.at_level(logging.DEBUG):
        assert delivery.drain(session, now=NOW + timedelta(days=30)).retrying == 1
    row = _attempts(session)[-1]
    assert token not in (row.last_error or "") and token not in caplog.text


# --- /v1/notifications/channels ----------------------------------------------


def test_channel_settings_api(session: Session, user: User, client: TestClient) -> None:
    h = _auth(user.id)  # type: ignore[arg-type]
    body = client.get("/v1/notifications/channels", headers=h).json()
    by = {c["channel"]: c for c in body["channels"]}
    assert set(by) == {"webhook", "email", "telegram"}
    assert by["webhook"]["available"] is True
    assert by["email"]["available"] is False and by["telegram"]["available"] is False
    assert "screen" in body["categories"] and "alert" in body["categories"]

    put = client.put(
        "/v1/notifications/channels",
        headers=h,
        json={
            "channels": [
                {
                    "channel": "webhook",
                    "enabled": True,
                    "url": HOOK,
                    "secret": SECRET,
                    "muted_categories": ["order"],
                }
            ]
        },
    )
    assert put.status_code == 200, put.text
    assert SECRET not in put.text
    hook = {c["channel"]: c for c in put.json()["channels"]}["webhook"]
    assert hook["enabled"] and hook["secret_set"] and hook["configured"]
    assert hook["url"] == HOOK and hook["muted_categories"] == ["order"]
    got = client.get("/v1/notifications/channels", headers=h)
    assert SECRET not in got.text
    # Leaving the secret out keeps it; an empty string removes it.
    keep = client.put(
        "/v1/notifications/channels", headers=h, json={"channels": [{"channel": "webhook"}]}
    )
    assert {c["channel"]: c for c in keep.json()["channels"]}["webhook"]["secret_set"] is True

    def status_of(change: dict) -> int:
        return client.put(
            "/v1/notifications/channels", headers=h, json={"channels": [change]}
        ).status_code

    assert status_of({"channel": "webhook", "secret": ""}) == 422  # enabled needs a secret
    assert status_of({"channel": "webhook", "url": "http://example.com/x"}) == 422
    assert status_of({"channel": "webhook", "url": "https://10.0.0.1/x"}) == 422
    assert status_of({"channel": "webhook", "url": "https://user:pw@example.com/x"}) == 422
    assert status_of({"channel": "webhook", "secret": "short"}) == 422
    assert status_of({"channel": "webhook", "muted_categories": ["nope"]}) == 422
    assert status_of({"channel": "email", "enabled": True}) == 409  # not on this server
    assert status_of({"channel": "telegram", "chat_id": "not a chat"}) == 422
    assert status_of({"channel": "telegram", "chat_id": "424242"}) == 200


def test_send_test_goes_through_the_real_sender(
    session: Session, user: User, client: TestClient, wire: Wire
) -> None:
    h = _auth(user.id)  # type: ignore[arg-type]
    assert client.post("/v1/notifications/channels/webhook/test", headers=h).status_code == 422
    assert client.post("/v1/notifications/channels/email/test", headers=h).status_code == 409
    client.put(
        "/v1/notifications/channels",
        headers=h,
        json={"channels": [{"channel": "webhook", "url": HOOK, "secret": SECRET}]},
    )
    ok = client.post("/v1/notifications/channels/webhook/test", headers=h).json()
    assert ok == {"channel": "webhook", "ok": True, "detail": "sent"}
    (request,) = wire.requests
    expected = "sha256=" + hmac.new(SECRET.encode(), request.content, hashlib.sha256).hexdigest()
    assert request.headers["x-stockviz-signature"] == expected
    wire.status = 500
    bad = client.post("/v1/notifications/channels/webhook/test", headers=h).json()
    assert bad["ok"] is False and bad["detail"] == "the webhook answered HTTP 500"
    assert _attempts(session) == []  # a test is not a delivery


def test_the_drain_job_is_recorded(session: Session, engine, user: User, wire, monkeypatch) -> None:
    _webhook(session, user)
    _notify(session, user)
    monkeypatch.setattr(cli, "engine", engine)
    assert "deliver-notifications" in cli.RECORDED_JOBS
    assert cli.main(["deliver-notifications"]) == 0
    assert len(wire.requests) == 1
