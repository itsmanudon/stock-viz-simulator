"""HTTP-level tests for /v1/leaderboard, /v1/profile."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from jose import jwt as jose_jwt
from sqlalchemy import event
from sqlmodel import Session, select

import stockviz.routers.leaderboard as lb_module
from stockviz.models import PortfolioSnapshot, User
from stockviz.schemas import ProfilePatchIn
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


def test_cached_leaderboard_obeys_privacy_commit_on_another_replica(
    session: Session, client: TestClient, engine
) -> None:
    hidden_id = _make_user(session, email="hidden@stockviz.dev", name="Hidden", public_profile=True)
    visible_id = _make_user(
        session, email="visible@stockviz.dev", name="Visible", public_profile=True
    )
    # Keep an old ORM instance resident: authorization must use fresh database values.
    stale_user = session.get(User, hidden_id)
    assert stale_user is not None
    assert len(client.get("/v1/leaderboard").json()) == 2
    with Session(engine) as other_replica:
        hidden = other_replica.get(User, hidden_id)
        assert hidden is not None
        hidden.public_profile = False
        other_replica.add(hidden)
        other_replica.commit()
    assert stale_user.public_profile is True

    entries = client.get("/v1/leaderboard").json()
    assert [entry["user_id"] for entry in entries] == [visible_id]
    assert entries[0]["rank"] == 1


def test_cached_leaderboard_filters_before_top_fifty(
    session: Session, client: TestClient, engine
) -> None:
    session.add_all(
        User(email=f"trader{i}@stockviz.dev", name=f"Trader {i}", public_profile=True)
        for i in range(52)
    )
    session.commit()
    first_page = client.get("/v1/leaderboard").json()
    removed_ids = {entry["user_id"] for entry in first_page[:2]}
    with Session(engine) as other_replica:
        for user_id in removed_ids:
            user = other_replica.get(User, user_id)
            assert user is not None
            user.public_profile = False
            other_replica.add(user)
        other_replica.commit()

    entries = client.get("/v1/leaderboard").json()
    assert len(entries) == 50
    assert [entry["rank"] for entry in entries] == list(range(1, 51))
    assert not removed_ids.intersection(entry["user_id"] for entry in entries)


def test_cache_fill_rechecks_privacy_after_concurrent_commit(
    session: Session, client: TestClient, engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    user_id = _make_user(session, public_profile=True)
    real_build = lb_module._build_leaderboard

    def build_with_concurrent_opt_out(build_session: Session):
        candidates = real_build(build_session)
        # The other replica commits after the fill read but before its publication.
        with Session(engine) as other_replica:
            lb_module.patch_profile(ProfilePatchIn(public_profile=False), other_replica, user_id)
        return candidates

    monkeypatch.setattr(lb_module, "_build_leaderboard", build_with_concurrent_opt_out)
    assert client.get("/v1/leaderboard").json() == []
    assert client.get("/v1/leaderboard").json() == []


def test_cached_leaderboard_uses_current_public_username(
    session: Session, client: TestClient, engine
) -> None:
    user_id = _make_user(session, name="Old identifying name", public_profile=True)
    assert client.get("/v1/leaderboard").json()[0]["username"] == "Old identifying name"
    with Session(engine) as other_replica:
        user = other_replica.get(User, user_id)
        assert user is not None
        user.name = "New public name"
        other_replica.add(user)
        other_replica.commit()

    assert client.get("/v1/leaderboard").json()[0]["username"] == "New public name"


def test_profile_cache_invalidation_occurs_after_durable_commit(
    session: Session, client: TestClient
) -> None:
    user_id = _make_user(session, public_profile=True)
    client.get("/v1/leaderboard")
    populated_at = lb_module._cache_ts
    timestamps_during_commit = []

    def observe_before_commit(commit_session):
        timestamps_during_commit.append(lb_module._cache_ts)

    event.listen(session, "before_commit", observe_before_commit)
    try:
        lb_module.patch_profile(ProfilePatchIn(public_profile=False), session, user_id)
    finally:
        event.remove(session, "before_commit", observe_before_commit)

    assert timestamps_during_commit == [populated_at]
    assert lb_module._cache_ts is None
    assert session.exec(select(User.public_profile).where(User.id == user_id)).one() is False


def test_failed_profile_commit_preserves_cache_and_durable_visibility(
    session: Session, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    user_id = _make_user(session, public_profile=True)
    client.get("/v1/leaderboard")
    populated_at = lb_module._cache_ts

    def fail_commit():
        raise RuntimeError("database commit failed")

    monkeypatch.setattr(session, "commit", fail_commit)
    with pytest.raises(RuntimeError, match="database commit failed"):
        lb_module.patch_profile(ProfilePatchIn(public_profile=False), session, user_id)
    session.rollback()

    assert lb_module._cache_ts == populated_at
    persisted_user = session.get(User, user_id)
    assert persisted_user is not None
    assert persisted_user.public_profile is True
    assert [entry["user_id"] for entry in client.get("/v1/leaderboard").json()] == [user_id]


def test_snapshot_count_query_runs_once_per_leaderboard_build(
    session: Session, client: TestClient, engine
) -> None:
    for i in range(3):
        user_id = _make_user(session, email=f"count{i}@stockviz.dev", public_profile=True)
        _add_snapshot(session, user_id, date(2026, 1, 1), Decimal("100000"))
    count_queries = []
    statements = []

    def observe_statement(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)
        if "count(" in statement.lower() and "portfolio_snapshots" in statement.lower():
            count_queries.append(statement)

    event.listen(engine, "before_cursor_execute", observe_statement)
    try:
        entries = client.get("/v1/leaderboard").json()
        assert len(statements) == 4
        statements.clear()
        cached_entries = client.get("/v1/leaderboard").json()
    finally:
        event.remove(engine, "before_cursor_execute", observe_statement)

    assert [entry["days_tracked"] for entry in entries] == [1, 1, 1]
    assert cached_entries == entries
    assert len(count_queries) == 1
    assert len(statements) == 1
