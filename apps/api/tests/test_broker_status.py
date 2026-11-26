"""A5.7 broker status and graceful degradation (M1.7).

Each state from the server's Kite settings and the recorded snapshot runs,
no secret in any response, per-user imported books, the Kite path of
``ingest-history`` recording its runs (Kite itself is never called), and the
nightly status and health leaving the by-hand snapshot out.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from jose import jwt as jose_jwt
from sqlmodel import Session, col, select

from stockviz._time import utcnow
from stockviz.main import app
from stockviz.models import BookKind, JobRun, User
from stockviz.services.books import create_book, update_book
from stockviz.services.brokers import (
    KITE_SNAPSHOT_JOB,
    OFFLINE_WINDOW,
    broker_statuses,
    record_provider_run,
)
from stockviz.settings import Settings, get_settings

SECRET = get_settings().internal_api_token
KEY = "kitekey-DO-NOT-LEAK-1234"
APP_SECRET = "kitesecret-DO-NOT-LEAK-5678"


def _h(user_id: int) -> dict[str, str]:
    token = jose_jwt.encode({"sub": str(user_id)}, SECRET, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


def _user(session: Session) -> int:
    user = User(email=f"{uuid4().hex}@stockviz.dev", name="Broker")
    session.add(user)
    session.commit()
    session.refresh(user)
    assert user.id is not None
    return user.id


def _settings(configured: bool) -> Settings:
    return get_settings().model_copy(
        update={
            "kite_api_key": KEY if configured else "",
            "kite_api_secret": APP_SECRET if configured else "",
        }
    )


@pytest.fixture
def kite_on():
    app.dependency_overrides[get_settings] = lambda: _settings(True)
    yield
    app.dependency_overrides.pop(get_settings, None)


@pytest.fixture
def kite_off():
    app.dependency_overrides[get_settings] = lambda: _settings(False)
    yield
    app.dependency_overrides.pop(get_settings, None)


def _run(session: Session, status: str, at: datetime) -> None:
    session.add(
        JobRun(
            job=KITE_SNAPSHOT_JOB,
            status=status,
            started_at=at,
            finished_at=at,
            exit_code=0 if status == "succeeded" else 1,
            error=None if status == "succeeded" else "Kite login failed",
        )
    )
    session.commit()


def _zerodha(client: TestClient, user_id: int) -> dict:
    res = client.get("/v1/broker/status", headers=_h(user_id))
    assert res.status_code == 200, res.text
    (item,) = res.json()["brokers"]
    assert item["broker"] == "zerodha" and item["provider"] == "kite"
    assert item["live_data"] is False
    return item


def test_needs_a_signed_in_user(client: TestClient) -> None:
    assert client.get("/v1/broker/status").status_code == 401


def test_not_configured_when_the_kite_app_is_blank(
    session: Session, client: TestClient, kite_off
) -> None:
    uid = _user(session)
    # A recorded success does not matter while the keys are blank.
    _run(session, "succeeded", utcnow() - timedelta(hours=2))
    item = _zerodha(client, uid)
    assert item["state"] == "not_configured" and item["configured"] is False


def test_half_a_kite_app_is_not_configured(session: Session) -> None:
    uid = _user(session)
    half = get_settings().model_copy(update={"kite_api_key": KEY, "kite_api_secret": ""})
    (status,) = broker_statuses(session, half, uid)
    assert status.state == "not_configured" and not status.configured


def test_not_connected_when_configured_and_never_snapshotted(
    session: Session, client: TestClient, kite_on
) -> None:
    uid = _user(session)
    item = _zerodha(client, uid)
    assert item["state"] == "not_connected" and item["configured"] is True
    assert item["last_snapshot_at"] is None and item["last_failure_at"] is None


def test_snapshot_only_after_a_successful_snapshot(
    session: Session, client: TestClient, kite_on
) -> None:
    uid = _user(session)
    at = utcnow() - timedelta(days=10)
    _run(session, "succeeded", at)
    item = _zerodha(client, uid)
    assert item["state"] == "snapshot_only"
    assert item["last_snapshot_at"].startswith(at.isoformat()[:16])


def test_offline_after_a_recent_provider_failure(
    session: Session, client: TestClient, kite_on
) -> None:
    uid = _user(session)
    _run(session, "succeeded", utcnow() - timedelta(days=10))
    _run(session, "failed", utcnow() - timedelta(hours=5))
    item = _zerodha(client, uid)
    assert item["state"] == "offline" and item["last_failure_at"] is not None
    assert "Kite login failed" not in client.get("/v1/broker/status", headers=_h(uid)).text


def test_an_old_failure_or_a_later_success_clears_offline(session: Session) -> None:
    uid = _user(session)
    on = _settings(True)
    now = utcnow()
    _run(session, "failed", now - OFFLINE_WINDOW - timedelta(hours=1))
    assert broker_statuses(session, on, uid, now=now)[0].state == "not_connected"
    _run(session, "succeeded", now - timedelta(days=20))
    assert broker_statuses(session, on, uid, now=now)[0].state == "snapshot_only"
    _run(session, "failed", now - timedelta(hours=1))
    assert broker_statuses(session, on, uid, now=now)[0].state == "offline"
    _run(session, "succeeded", now - timedelta(minutes=5))
    assert broker_statuses(session, on, uid, now=now)[0].state == "snapshot_only"


def test_no_key_or_secret_in_the_response(session: Session, client: TestClient, kite_on) -> None:
    uid = _user(session)
    _run(session, "failed", utcnow())
    text = client.get("/v1/broker/status", headers=_h(uid)).text
    assert KEY not in text and APP_SECRET not in text
    assert "kitekey" not in text and "secret" not in text.lower()


def test_imported_books_are_per_user_and_skip_archived(
    session: Session, client: TestClient, kite_on
) -> None:
    alice, bob = _user(session), _user(session)
    create_book(session, user_id=alice, name="Zerodha main", kind=BookKind.IMPORTED)
    old = create_book(session, user_id=alice, name="Zerodha old", kind=BookKind.IMPORTED)
    assert old.id is not None
    update_book(session, user_id=alice, book_id=old.id, archived=True)
    create_book(session, user_id=alice, name="Paper two")
    a, b = _zerodha(client, alice), _zerodha(client, bob)
    assert a["imported_books"] == 1 and b["imported_books"] == 0
    # A5.3 fills the import time; nothing imports yet.
    assert a["last_imported_at"] is None


def test_record_provider_run_keeps_a_fixed_summary(session: Session) -> None:
    row = record_provider_run(session, KITE_SNAPSHOT_JOB, ok=False, summary="Kite login failed")
    assert row.status == "failed" and row.exit_code == 1 and row.error == "Kite login failed"
    ok = record_provider_run(session, KITE_SNAPSHOT_JOB, ok=True, summary="ignored")
    assert ok.status == "succeeded" and ok.error is None


def test_status_and_health_leave_the_snapshot_out(session: Session, client: TestClient) -> None:
    _run(session, "failed", utcnow())
    body = client.get("/v1/status").json()
    assert KITE_SNAPSHOT_JOB not in {j["job"] for j in body["jobs"]}
    health = client.get("/health").json()
    assert KITE_SNAPSHOT_JOB not in (health.get("failing_jobs") or [])


def _kite_cli(monkeypatch, engine) -> None:
    from stockviz import cli

    monkeypatch.setenv("KITE_API_KEY", KEY)
    monkeypatch.setenv("KITE_API_SECRET", APP_SECRET)
    cli.get_settings.cache_clear()
    monkeypatch.setattr(cli, "engine", engine)


def _rows(session: Session) -> list[JobRun]:
    session.expire_all()
    return list(
        session.exec(
            select(JobRun).where(JobRun.job == KITE_SNAPSHOT_JOB).order_by(col(JobRun.id))
        ).all()
    )


def test_cli_records_a_failed_kite_login_without_the_token(
    monkeypatch, engine, session: Session, capsys
) -> None:
    from stockviz import cli
    from stockviz.services.ingest.providers import kite

    _kite_cli(monkeypatch, engine)

    def refuse(api_key, api_secret, request_token, **_):
        raise kite.KiteError("Kite 403: TokenException: Token is invalid or has expired.")

    monkeypatch.setattr(kite, "open_session", refuse)
    try:
        code = cli.main(
            ["ingest-history", "--provider", "kite", "--request-token", "req-TOKEN-xyz"]
        )
    finally:
        cli.get_settings.cache_clear()
    assert code == 1
    (row,) = _rows(session)
    assert row.status == "failed" and row.error == "Kite login failed"
    assert "req-TOKEN-xyz" not in capsys.readouterr().out


def test_cli_records_success_and_ticker_misses_are_not_provider_errors(
    monkeypatch, engine, session: Session
) -> None:
    from stockviz import cli
    from stockviz.services.ingest import history
    from stockviz.services.ingest.providers import kite

    _kite_cli(monkeypatch, engine)

    class FakeClient:
        def instrument_tokens(self, exchange):
            return {"RELIANCE": 1}

        def daily_bars(self, ticker, token, *, end):
            return []

    monkeypatch.setattr(kite, "open_session", lambda *a, **k: FakeClient())

    def fake_snapshot(session, tickers, fetch, *, scheme, apply):
        out = []
        for t in tickers:
            try:
                fetch(t)
                out.append(history.TickerReport(ticker=t))
            except Exception as exc:
                out.append(history.TickerReport(ticker=t, error=str(exc)))
        return out

    monkeypatch.setattr(history, "snapshot", fake_snapshot)
    try:
        # TCS.NS is not in the fake list: a ticker miss, not a provider error.
        cli.main(["ingest-history", "--provider", "kite", "--request-token", "r", "RELIANCE.NS", "TCS.NS"])  # fmt: skip
    finally:
        cli.get_settings.cache_clear()
    (row,) = _rows(session)
    assert row.status == "succeeded"


def test_cli_records_a_provider_error_mid_snapshot(monkeypatch, engine, session: Session) -> None:
    from stockviz import cli
    from stockviz.services.ingest import history
    from stockviz.services.ingest.providers import kite

    _kite_cli(monkeypatch, engine)

    class Failing:
        def instrument_tokens(self, exchange):
            raise kite.KiteError("Kite instruments NSE: HTTP 503")

    monkeypatch.setattr(kite, "open_session", lambda *a, **k: Failing())

    def fake_snapshot(session, tickers, fetch, *, scheme, apply):
        out = []
        for t in tickers:
            try:
                fetch(t)
            except Exception as exc:
                out.append(history.TickerReport(ticker=t, error=str(exc)))
        return out

    monkeypatch.setattr(history, "snapshot", fake_snapshot)
    try:
        code = cli.main(["ingest-history", "--provider", "kite", "--request-token", "r", "RELIANCE.NS"])  # fmt: skip
    finally:
        cli.get_settings.cache_clear()
    assert code == 1
    (row,) = _rows(session)
    assert row.status == "failed" and row.error == "Kite error on 1 ticker(s)"


def test_cli_without_keys_records_nothing(monkeypatch, engine, session: Session) -> None:
    from stockviz import cli

    monkeypatch.delenv("KITE_API_KEY", raising=False)
    monkeypatch.delenv("KITE_API_SECRET", raising=False)
    cli.get_settings.cache_clear()
    monkeypatch.setattr(cli, "engine", engine)
    try:
        assert cli.main(["ingest-history", "--provider", "kite", "--request-token", "x"]) == 2
    finally:
        cli.get_settings.cache_clear()
    assert _rows(session) == []
