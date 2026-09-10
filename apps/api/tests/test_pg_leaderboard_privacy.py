"""PostgreSQL visibility checks with independent sessions and a warm ranking cache.

Only the throwaway database from tests.pg_scratch is used. Missing/non-Postgres
DATABASE_URL skips these tests; PostgreSQL connection or assertion errors fail.
"""

from __future__ import annotations

import pytest
from sqlmodel import Session

import stockviz.routers.leaderboard as leaderboard
from stockviz.models import User
from stockviz.schemas import LeaderboardEntryOut, ProfilePatchIn
from tests.pg_scratch import postgres_admin_url, scratch_postgres_engine

pytestmark = pytest.mark.skipif(
    postgres_admin_url() is None,
    reason="DATABASE_URL is not PostgreSQL",
)


@pytest.fixture(autouse=True)
def isolated_ranking_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(leaderboard, "_cache", [])
    monkeypatch.setattr(leaderboard, "_cache_ts", None)


def _public_user(session: Session) -> int:
    user = User(email="leaderboard-privacy@stockviz.dev", name="Public Trader", public_profile=True)
    session.add(user)
    session.commit()
    session.refresh(user)
    assert user.id is not None
    return user.id


def test_committed_opt_out_bypasses_cached_ranking_and_stale_identity_map() -> None:
    with scratch_postgres_engine() as engine:
        with Session(engine) as setup:
            user_id = _public_user(setup)

        with Session(engine) as reader, Session(engine) as writer:
            resident_user = reader.get(User, user_id)
            assert resident_user is not None
            assert [entry.user_id for entry in leaderboard.get_leaderboard(reader)] == [user_id]
            populated_at = leaderboard._cache_ts

            changed_user = writer.get(User, user_id)
            assert changed_user is not None
            changed_user.public_profile = False
            writer.add(changed_user)
            writer.commit()  # A different replica does not invalidate this process's cache.

            assert leaderboard._cache_ts == populated_at
            assert resident_user.public_profile is True
            assert leaderboard.get_leaderboard(reader) == []


def test_uncommitted_opt_out_and_rollback_preserve_committed_public_visibility() -> None:
    with scratch_postgres_engine() as engine:
        with Session(engine) as setup:
            user_id = _public_user(setup)

        with Session(engine) as reader, Session(engine) as writer:
            assert [entry.user_id for entry in leaderboard.get_leaderboard(reader)] == [user_id]
            populated_at = leaderboard._cache_ts
            changed_user = writer.get(User, user_id)
            assert changed_user is not None
            changed_user.public_profile = False
            writer.add(changed_user)
            writer.flush()

            assert [entry.user_id for entry in leaderboard.get_leaderboard(reader)] == [user_id]
            writer.rollback()

            assert leaderboard._cache_ts == populated_at
            assert [entry.user_id for entry in leaderboard.get_leaderboard(reader)] == [user_id]


def test_cache_fill_rechecks_committed_privacy_on_its_next_statement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with scratch_postgres_engine() as engine:
        with Session(engine) as setup:
            user_id = _public_user(setup)

        build = leaderboard._build_leaderboard

        def build_across_opt_out(session: Session) -> list[LeaderboardEntryOut]:
            candidates = build(session)
            with Session(engine) as writer:
                leaderboard.patch_profile(ProfilePatchIn(public_profile=False), writer, user_id)
            return candidates

        monkeypatch.setattr(leaderboard, "_build_leaderboard", build_across_opt_out)
        with Session(engine) as reader:
            assert leaderboard.get_leaderboard(reader) == []
            assert leaderboard.get_leaderboard(reader) == []
