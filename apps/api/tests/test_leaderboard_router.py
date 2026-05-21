"""HTTP-level tests for /v1/leaderboard, /v1/profile."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from jose import jwt as jose_jwt
from sqlmodel import Session

import stockviz.routers.leaderboard as lb_module
from stockviz.models import PortfolioSnapshot, User
from stockviz.settings import get_settings

SECRET = get_settings().internal_api_token


def _auth_headers(user_id: int) -> dict[str, str]:
    token = jose_jwt.encode({"sub": str(user_id)}, SECRET, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


def _make_user(
    session: Session,
    email: str = "trader@stockviz.dev",
    name: str = "Trader",
    public_profile: bool = False,
) -> int:
    user = User(email=email, name=name, public_profile=public_profile)
    session.add(user)
    session.commit()
    session.refresh(user)
    assert user.id is not None
    return user.id


def _add_snapshot(session: Session, user_id: int, d: date, nav: Decimal) -> None:
    session.add(PortfolioSnapshot(user_id=user_id, date=d, nav=nav))
    session.commit()


@pytest.fixture(autouse=True)
def _reset_cache():
    """Reset the leaderboard cache to its never-populated state before/after
    every test, so a cache entry from one test (built against a different
    in-memory DB) can't leak into the next."""
    lb_module._cache_ts = None
    lb_module._cache = []
    yield
    lb_module._cache_ts = None
    lb_module._cache = []


# ---------------------------------------------------------------------------
# GET /v1/leaderboard
# ---------------------------------------------------------------------------


def test_leaderboard_is_public(client: TestClient) -> None:
    response = client.get("/v1/leaderboard")
    assert response.status_code == 200
    assert response.json() == []


def test_leaderboard_omits_private_users(session: Session, client: TestClient) -> None:
    _make_user(session, email="private@stockviz.dev", public_profile=False)
    response = client.get("/v1/leaderboard")
    assert response.json() == []


def test_leaderboard_includes_public_user(session: Session, client: TestClient) -> None:
    user_id = _make_user(
        session, email="public@stockviz.dev", name="Public Pete", public_profile=True
    )
    _add_snapshot(session, user_id, date(2026, 1, 1), Decimal("100000"))
    _add_snapshot(session, user_id, date(2026, 5, 1), Decimal("120000"))

    entries = client.get("/v1/leaderboard").json()
    assert len(entries) == 1
    entry = entries[0]
    assert entry["rank"] == 1
    assert entry["username"] == "Public Pete"
    assert abs(entry["return_pct"] - 20.0) < 0.01


def test_leaderboard_ranked_by_return(session: Session, client: TestClient) -> None:
    uid_a = _make_user(session, email="alpha@stockviz.dev", name="Alpha", public_profile=True)
    uid_b = _make_user(session, email="beta@stockviz.dev", name="Beta", public_profile=True)

    _add_snapshot(session, uid_a, date(2026, 1, 1), Decimal("100000"))
    _add_snapshot(session, uid_a, date(2026, 5, 1), Decimal("110000"))  # +10%

    _add_snapshot(session, uid_b, date(2026, 1, 1), Decimal("100000"))
    _add_snapshot(session, uid_b, date(2026, 5, 1), Decimal("150000"))  # +50%

    entries = client.get("/v1/leaderboard").json()
    assert len(entries) == 2
    assert entries[0]["username"] == "Beta"
    assert entries[0]["rank"] == 1
    assert entries[1]["username"] == "Alpha"
    assert entries[1]["rank"] == 2


def test_leaderboard_no_snapshot_shows_zero_return(session: Session, client: TestClient) -> None:
    _make_user(session, email="new@stockviz.dev", name="New Trader", public_profile=True)
    entries = client.get("/v1/leaderboard").json()
    assert len(entries) == 1
    assert entries[0]["return_pct"] == 0.0


def test_leaderboard_username_falls_back_to_email_prefix(
    session: Session, client: TestClient
) -> None:
    user = User(email="noname@stockviz.dev", name=None, public_profile=True)
    session.add(user)
    session.commit()

    entries = client.get("/v1/leaderboard").json()
    assert entries[0]["username"] == "noname"


# ---------------------------------------------------------------------------
# GET /v1/profile
# ---------------------------------------------------------------------------


def test_get_profile_requires_auth(client: TestClient) -> None:
    assert client.get("/v1/profile").status_code == 401


def test_get_profile_returns_flag(session: Session, client: TestClient) -> None:
    user_id = _make_user(session, public_profile=True)
    resp = client.get("/v1/profile", headers=_auth_headers(user_id))
    assert resp.status_code == 200
    body = resp.json()
    assert body["user_id"] == user_id
    assert body["public_profile"] is True


# ---------------------------------------------------------------------------
# PATCH /v1/profile
# ---------------------------------------------------------------------------


def test_patch_profile_requires_auth(client: TestClient) -> None:
    assert client.patch("/v1/profile", json={"public_profile": True}).status_code == 401


def test_patch_profile_toggles_visibility(session: Session, client: TestClient) -> None:
    user_id = _make_user(session, public_profile=False)
    headers = _auth_headers(user_id)

    resp = client.patch("/v1/profile", json={"public_profile": True}, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["public_profile"] is True

    # Verify persisted
    resp2 = client.get("/v1/profile", headers=headers)
    assert resp2.json()["public_profile"] is True


def test_patch_profile_invalidates_cache(session: Session, client: TestClient) -> None:
    user_id = _make_user(
        session, email="cache@stockviz.dev", name="Cacheable", public_profile=False
    )
    headers = _auth_headers(user_id)

    # Warm the cache — user is hidden
    entries_before = client.get("/v1/leaderboard").json()
    assert len(entries_before) == 0

    # Opt in — cache should be invalidated
    client.patch("/v1/profile", json={"public_profile": True}, headers=headers)

    entries_after = client.get("/v1/leaderboard").json()
    assert len(entries_after) == 1
    assert entries_after[0]["username"] == "Cacheable"
