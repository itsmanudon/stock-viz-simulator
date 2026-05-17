"""HTTP-level tests for /v1/symbols/{ticker}/comments and /v1/comments/{id}."""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from jose import jwt as jose_jwt
from sqlmodel import Session

from stockviz.models import Comment, Symbol, User
from stockviz.settings import get_settings

SECRET = get_settings().internal_api_token


def _auth(user_id: int) -> dict[str, str]:
    token = jose_jwt.encode({"sub": str(user_id)}, SECRET, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


def _make_user(session: Session, email: str, name: str = "User") -> int:
    user = User(email=email, name=name)
    session.add(user)
    session.commit()
    session.refresh(user)
    assert user.id is not None
    return user.id


def _seed_symbol(session: Session, ticker: str = "AAPL") -> None:
    session.add(Symbol(ticker=ticker, name=f"{ticker} Inc."))
    session.commit()


# ---------------------------------------------------------------------------
# GET
# ---------------------------------------------------------------------------


def test_list_comments_empty(session: Session, client: TestClient) -> None:
    _seed_symbol(session)
    response = client.get("/v1/symbols/AAPL/comments")
    assert response.status_code == 200
    assert response.json() == []


def test_list_comments_404_on_unknown_symbol(client: TestClient) -> None:
    response = client.get("/v1/symbols/NOPE/comments")
    assert response.status_code == 404


def test_list_comments_returns_newest_first(session: Session, client: TestClient) -> None:
    _seed_symbol(session)
    user_id = _make_user(session, "a@x.dev", name="Alice")
    base = datetime(2025, 4, 10, 12, 0)
    for i in range(3):
        session.add(
            Comment(
                user_id=user_id,
                ticker="AAPL",
                body=f"hello {i}",
                created_at=base + timedelta(minutes=i),
            )
        )
    session.commit()
    response = client.get("/v1/symbols/AAPL/comments")
    bodies = [c["body"] for c in response.json()]
    assert bodies == ["hello 2", "hello 1", "hello 0"]


def test_list_comments_inlines_replies(session: Session, client: TestClient) -> None:
    _seed_symbol(session)
    user_id = _make_user(session, "a@x.dev", name="Alice")
    parent = Comment(user_id=user_id, ticker="AAPL", body="top-level")
    session.add(parent)
    session.commit()
    session.refresh(parent)
    reply = Comment(user_id=user_id, ticker="AAPL", body="a reply", parent_id=parent.id)
    session.add(reply)
    session.commit()

    response = client.get("/v1/symbols/AAPL/comments")
    body = response.json()
    # Only one top-level row; replies inlined under it.
    assert len(body) == 1
    assert body[0]["body"] == "top-level"
    assert len(body[0]["replies"]) == 1
    assert body[0]["replies"][0]["body"] == "a reply"
    assert body[0]["user_name"] == "Alice"


def test_list_comments_pagination(session: Session, client: TestClient) -> None:
    _seed_symbol(session)
    user_id = _make_user(session, "a@x.dev")
    base = datetime(2025, 4, 10, 12, 0)
    for i in range(5):
        session.add(
            Comment(
                user_id=user_id,
                ticker="AAPL",
                body=f"c{i}",
                created_at=base + timedelta(minutes=i),
            )
        )
    session.commit()
    page1 = client.get("/v1/symbols/AAPL/comments?limit=2").json()
    page2 = client.get("/v1/symbols/AAPL/comments?limit=2&offset=2").json()
    assert [c["body"] for c in page1] == ["c4", "c3"]
    assert [c["body"] for c in page2] == ["c2", "c1"]


# ---------------------------------------------------------------------------
# POST
# ---------------------------------------------------------------------------


def test_post_comment_requires_auth(session: Session, client: TestClient) -> None:
    _seed_symbol(session)
    response = client.post("/v1/symbols/AAPL/comments", json={"body": "hello"})
    assert response.status_code == 401


def test_post_comment_creates_row(session: Session, client: TestClient) -> None:
    _seed_symbol(session)
    user_id = _make_user(session, "a@x.dev", name="Alice")
    response = client.post(
        "/v1/symbols/AAPL/comments",
        headers=_auth(user_id),
        json={"body": "  hello world  "},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["body"] == "hello world"  # trimmed
    assert body["user_id"] == user_id
    assert body["user_name"] == "Alice"
    assert body["ticker"] == "AAPL"


def test_post_comment_rejects_empty_body(session: Session, client: TestClient) -> None:
    _seed_symbol(session)
    user_id = _make_user(session, "a@x.dev")
    response = client.post(
        "/v1/symbols/AAPL/comments",
        headers=_auth(user_id),
        json={"body": "   "},
    )
    assert response.status_code == 400


def test_post_comment_404_on_unknown_symbol(session: Session, client: TestClient) -> None:
    user_id = _make_user(session, "a@x.dev")
    response = client.post(
        "/v1/symbols/NOPE/comments",
        headers=_auth(user_id),
        json={"body": "hi"},
    )
    assert response.status_code == 404


def test_post_reply_to_top_level(session: Session, client: TestClient) -> None:
    _seed_symbol(session)
    user_id = _make_user(session, "a@x.dev")
    parent_id = client.post(
        "/v1/symbols/AAPL/comments",
        headers=_auth(user_id),
        json={"body": "first"},
    ).json()["id"]
    response = client.post(
        "/v1/symbols/AAPL/comments",
        headers=_auth(user_id),
        json={"body": "reply", "parent_id": parent_id},
    )
    assert response.status_code == 201
    assert response.json()["parent_id"] == parent_id


def test_post_reply_to_reply_rejected(session: Session, client: TestClient) -> None:
    _seed_symbol(session)
    user_id = _make_user(session, "a@x.dev")
    parent = client.post(
        "/v1/symbols/AAPL/comments",
        headers=_auth(user_id),
        json={"body": "first"},
    ).json()
    reply = client.post(
        "/v1/symbols/AAPL/comments",
        headers=_auth(user_id),
        json={"body": "reply", "parent_id": parent["id"]},
    ).json()
    response = client.post(
        "/v1/symbols/AAPL/comments",
        headers=_auth(user_id),
        json={"body": "deep", "parent_id": reply["id"]},
    )
    assert response.status_code == 400


def test_post_rate_limit_returns_429(session: Session, client: TestClient) -> None:
    _seed_symbol(session)
    user_id = _make_user(session, "spammer@x.dev")
    headers = _auth(user_id)
    for _ in range(5):
        ok = client.post("/v1/symbols/AAPL/comments", headers=headers, json={"body": "x"})
        assert ok.status_code == 201
    # 6th post within the same minute → 429.
    blocked = client.post("/v1/symbols/AAPL/comments", headers=headers, json={"body": "y"})
    assert blocked.status_code == 429


# ---------------------------------------------------------------------------
# DELETE
# ---------------------------------------------------------------------------


def test_delete_own_comment(session: Session, client: TestClient) -> None:
    _seed_symbol(session)
    user_id = _make_user(session, "a@x.dev")
    created = client.post(
        "/v1/symbols/AAPL/comments",
        headers=_auth(user_id),
        json={"body": "hi"},
    ).json()
    response = client.delete(f"/v1/comments/{created['id']}", headers=_auth(user_id))
    assert response.status_code == 204
    assert client.get("/v1/symbols/AAPL/comments").json() == []


def test_delete_others_comment_returns_404(session: Session, client: TestClient) -> None:
    _seed_symbol(session)
    alice = _make_user(session, "a@x.dev")
    bob = _make_user(session, "b@x.dev")
    alice_comment = client.post(
        "/v1/symbols/AAPL/comments",
        headers=_auth(alice),
        json={"body": "mine"},
    ).json()
    response = client.delete(f"/v1/comments/{alice_comment['id']}", headers=_auth(bob))
    assert response.status_code == 404
    # And alice's comment still exists.
    assert len(client.get("/v1/symbols/AAPL/comments").json()) == 1


def test_delete_top_level_also_drops_replies(session: Session, client: TestClient) -> None:
    _seed_symbol(session)
    user_id = _make_user(session, "a@x.dev")
    parent = client.post(
        "/v1/symbols/AAPL/comments",
        headers=_auth(user_id),
        json={"body": "first"},
    ).json()
    client.post(
        "/v1/symbols/AAPL/comments",
        headers=_auth(user_id),
        json={"body": "reply", "parent_id": parent["id"]},
    )
    response = client.delete(f"/v1/comments/{parent['id']}", headers=_auth(user_id))
    assert response.status_code == 204
    # Both parent and reply gone.
    assert client.get("/v1/symbols/AAPL/comments").json() == []
