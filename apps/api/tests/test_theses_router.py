"""A2.2: /v1/theses, a written view on one instrument with a DSL kill rule."""

from __future__ import annotations

from fastapi.testclient import TestClient
from jose import jwt as jose_jwt
from sqlmodel import Session

from stockviz.models import User
from stockviz.services.dsl import compile_rule
from stockviz.settings import get_settings
from tests.symbols import seed_symbols

SECRET = get_settings().internal_api_token


def _auth(user_id: int) -> dict[str, str]:
    return {
        "Authorization": "Bearer "
        + jose_jwt.encode({"sub": str(user_id)}, SECRET, algorithm="HS256")
    }


def _user(session: Session, email: str) -> int:
    user = User(email=email, name="T")
    session.add(user)
    session.commit()
    session.refresh(user)
    assert user.id is not None
    return user.id


def test_theses_require_auth(client: TestClient) -> None:
    assert client.get("/v1/theses").status_code == 401
    assert client.post("/v1/theses", json={}).status_code == 401


def test_create_list_update_close(session: Session, client: TestClient) -> None:
    seed_symbols(session, "AAPL")
    uid = _user(session, "a@x.dev")
    created = client.post(
        "/v1/theses",
        json={
            "ticker": "aapl",
            "title": "Services margin",
            "body": "Services keep growing faster than hardware.",
            "kill_rule": "close < sma(close, 200)",
        },
        headers=_auth(uid),
    )
    assert created.status_code == 201
    body = created.json()
    assert body["ticker"] == "AAPL" and body["status"] == "open"
    assert body["kill_rule_hash"] == compile_rule("close < sma(close, 200)").hash

    tid = body["id"]
    patched = client.patch(
        f"/v1/theses/{tid}", json={"title": "Services"}, headers=_auth(uid)
    ).json()
    assert patched["title"] == "Services" and patched["kill_rule_text"] == "close < sma(close, 200)"
    cleared = client.patch(f"/v1/theses/{tid}", json={"kill_rule": None}, headers=_auth(uid))
    assert cleared.json()["kill_rule_text"] is None and cleared.json()["kill_rule_hash"] is None

    closed = client.post(
        f"/v1/theses/{tid}/close", json={"status": "invalidated"}, headers=_auth(uid)
    )
    assert closed.json()["status"] == "invalidated"
    assert client.post(f"/v1/theses/{tid}/close", headers=_auth(uid)).status_code == 409
    assert (
        client.patch(f"/v1/theses/{tid}", json={"title": "x"}, headers=_auth(uid)).status_code
        == 409
    )

    assert [t["id"] for t in client.get("/v1/theses", headers=_auth(uid)).json()] == [tid]
    assert client.get("/v1/theses?status=open", headers=_auth(uid)).json() == []
    assert len(client.get("/v1/theses?status=invalidated", headers=_auth(uid)).json()) == 1


def test_kill_rule_must_compile(session: Session, client: TestClient) -> None:
    seed_symbols(session, "AAPL")
    uid = _user(session, "a@x.dev")
    res = client.post(
        "/v1/theses",
        json={"ticker": "AAPL", "title": "t", "body": "b", "kill_rule": "close <"},
        headers=_auth(uid),
    )
    assert res.status_code == 422 and res.json()["detail"]["kind"] == "syntax"
    tid = client.post(
        "/v1/theses", json={"ticker": "AAPL", "title": "t", "body": "b"}, headers=_auth(uid)
    ).json()["id"]
    bad = client.patch(f"/v1/theses/{tid}", json={"kill_rule": "rsi(14)"}, headers=_auth(uid))
    assert bad.status_code == 422 and bad.json()["detail"]["kind"] == "type"


def test_unknown_symbol_and_other_users(session: Session, client: TestClient) -> None:
    seed_symbols(session, "AAPL")
    a, b = _user(session, "a@x.dev"), _user(session, "b@x.dev")
    assert (
        client.post(
            "/v1/theses", json={"ticker": "NOPE", "title": "t", "body": "b"}, headers=_auth(a)
        ).status_code
        == 404
    )
    tid = client.post(
        "/v1/theses", json={"ticker": "AAPL", "title": "t", "body": "b"}, headers=_auth(a)
    ).json()["id"]
    assert client.get("/v1/theses", headers=_auth(b)).json() == []
    assert (
        client.patch(f"/v1/theses/{tid}", json={"title": "x"}, headers=_auth(b)).status_code == 404
    )
    assert client.post(f"/v1/theses/{tid}/close", headers=_auth(b)).status_code == 404
