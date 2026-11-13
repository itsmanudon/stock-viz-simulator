"""`/v1/leaderboard` and `/v1/profile` — public rankings + opt-in visibility.

GET /v1/leaderboard  — public; returns top 50 users by return % who have
                       opted in. Rankings are cached in-process for one hour;
                       visibility and names are read from the DB on every call.

GET /v1/profile      — authed; returns the caller's public_profile flag.
PATCH /v1/profile    — authed; sets public_profile true/false.
"""

from __future__ import annotations

import secrets
import time
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func
from sqlmodel import Session, select

from stockviz.auth import UserIdDep
from stockviz.db import get_session
from stockviz.limiter import limiter
from stockviz.models import Portfolio, PortfolioSnapshot
from stockviz.models.user import User
from stockviz.schemas import LeaderboardEntryOut, ProfileOut, ProfilePatchIn

router = APIRouter(prefix="/v1", tags=["leaderboard"])

SessionDep = Annotated[Session, Depends(get_session)]

_INITIAL_NAV = Decimal("100000")
_CACHE_TTL = 3600  # seconds

MIN_SNAPSHOTS_TO_RANK = 30
"""Days of tracked history before an account is ranked against the field.

Return-since-inception over an arbitrary window with no minimum lets a single
lucky trade top the board. Shorter-lived accounts still appear, sorted below
everyone who qualifies, with ``ranked: false`` so the UI can mark them.
"""

# ``_cache_ts`` is the ``time.monotonic()`` reading when ``_cache`` was last
# built, or ``None`` when the cache has never been populated (or was
# invalidated). A ``None`` sentinel — rather than ``0.0`` — matters because
# ``time.monotonic()``'s zero point is arbitrary: on a freshly-booted host it
# can read below ``_CACHE_TTL``, so ``monotonic() - 0.0`` would wrongly look
# "fresh" and the endpoint would serve an empty leaderboard for the first hour
# after deploy.
# Each entry keeps its user id beside it for the visibility check; the id is
# never part of the response (audit SR-12).
_cache: list[tuple[int, LeaderboardEntryOut]] = []
_cache_ts: float | None = None


def _first_and_last_navs(
    session: Session, user_ids: list[int]
) -> dict[int, tuple[Decimal, Decimal]]:
    """(first, last) NAV per user, from one pass over the snapshot table.

    The previous version issued a full snapshot-history query per public user,
    so the leaderboard cost grew with both the number of opted-in users and the
    length of their history.
    """
    if not user_ids:
        return {}

    ranked = select(
        PortfolioSnapshot.user_id,
        PortfolioSnapshot.nav,  # type: ignore[arg-type]
        func.row_number()
        .over(
            partition_by=PortfolioSnapshot.user_id,  # type: ignore[arg-type]
            order_by=PortfolioSnapshot.date.asc(),  # type: ignore[attr-defined]
        )
        .label("rn_asc"),
        func.row_number()
        .over(
            partition_by=PortfolioSnapshot.user_id,  # type: ignore[arg-type]
            order_by=PortfolioSnapshot.date.desc(),  # type: ignore[attr-defined]
        )
        .label("rn_desc"),
    ).where(PortfolioSnapshot.user_id.in_(user_ids))  # type: ignore[attr-defined]
    sub = ranked.subquery()

    rows = session.exec(
        select(sub.c.user_id, sub.c.nav, sub.c.rn_asc, sub.c.rn_desc).where(  # type: ignore[call-overload]
            (sub.c.rn_asc == 1) | (sub.c.rn_desc == 1)
        )
    ).all()

    first: dict[int, Decimal] = {}
    last: dict[int, Decimal] = {}
    for user_id, nav, rn_asc, rn_desc in rows:
        if rn_asc == 1:
            first[user_id] = nav
        if rn_desc == 1:
            last[user_id] = nav
    return {uid: (first[uid], last[uid]) for uid in first if uid in last}


HANDLE_PREFIX = "trader-"


def ensure_public_handle(session: Session, user: User) -> str:
    """The user's opaque public handle, made once (SR-12). Commits when new."""
    if user.public_handle:
        return user.public_handle
    while True:
        candidate = f"{HANDLE_PREFIX}{secrets.token_hex(3)}"
        clash = session.exec(select(User.id).where(User.public_handle == candidate)).first()
        if clash is None:
            break
    user.public_handle = candidate
    session.add(user)
    session.commit()
    session.refresh(user)
    return candidate


def _public_name(display_name: str | None, handle: str) -> str:
    return display_name or handle


def _build_leaderboard(session: Session) -> list[tuple[int, LeaderboardEntryOut]]:
    public_users = list(session.exec(select(User).where(User.public_profile.is_(True))))  # type: ignore[union-attr]
    for user in public_users:
        ensure_public_handle(session, user)
    user_ids = [u.id for u in public_users if u.id is not None]
    navs_by_user = _first_and_last_navs(session, user_ids)
    snapshot_counts = _snapshot_counts(session)
    # LG-1: measure from the fixed opening value, not the first snapshot, which
    # the nightly job overwrites when the user trades on the opening day.
    portfolios = (
        list(session.exec(select(Portfolio).where(Portfolio.user_id.in_(user_ids))))  # type: ignore[attr-defined]
        if user_ids
        else []
    )
    opening_by_user: dict[int, Decimal] = {p.user_id: p.opening_nav for p in portfolios}
    # Phase 4.8: NAVs are in each account's base currency; returns compare.
    base_by_user: dict[int, str] = {p.user_id: p.base_currency or "USD" for p in portfolios}

    entries: list[tuple[float, Decimal, int, User]] = []
    for user in public_users:
        opening = opening_by_user.get(user.id or -1)
        fallback = opening if opening is not None else _INITIAL_NAV
        first_nav, current_nav = navs_by_user.get(user.id or -1, (fallback, fallback))
        initial_nav = opening if opening is not None else first_nav
        snapshot_count = snapshot_counts.get(user.id or -1, 0)

        return_pct = (
            float((current_nav - initial_nav) / initial_nav * 100) if initial_nav > 0 else 0.0
        )
        entries.append((return_pct, current_nav, snapshot_count, user))

    # Users without a real track record can't be ranked meaningfully: a single
    # lucky day would otherwise top the board. They still appear, but below
    # everyone who has qualified.
    entries.sort(key=lambda t: (t[2] >= MIN_SNAPSHOTS_TO_RANK, t[0]), reverse=True)

    return [
        (
            user.id,  # type: ignore[misc]
            LeaderboardEntryOut(
                rank=rank,
                handle=user.public_handle or "",
                username=_public_name(user.display_name, user.public_handle or ""),
                return_pct=round(return_pct, 4),
                portfolio_value=nav,
                currency=base_by_user.get(user.id or -1, "USD"),
                days_tracked=snapshot_count,
                ranked=snapshot_count >= MIN_SNAPSHOTS_TO_RANK,
            ),
        )
        for rank, (return_pct, nav, snapshot_count, user) in enumerate(entries, start=1)
    ]


def _snapshot_counts(session: Session) -> dict[int, int]:
    """Snapshots per user, cached for the life of one leaderboard build."""
    rows = session.exec(
        select(PortfolioSnapshot.user_id, func.count()).group_by(PortfolioSnapshot.user_id)  # type: ignore[call-overload]
    ).all()
    return dict(rows)


@router.get("/leaderboard", response_model=list[LeaderboardEntryOut])
@limiter.limit("30/minute")
def get_leaderboard(request: Request, session: SessionDep) -> list[LeaderboardEntryOut]:
    return visible_leaderboard(session)


def visible_leaderboard(session: Session) -> list[LeaderboardEntryOut]:
    """The public top 50, cache-backed, visibility read from the database."""
    global _cache, _cache_ts
    if _cache_ts is None or time.monotonic() - _cache_ts > _CACHE_TTL:
        _cache = _build_leaderboard(session)
        _cache_ts = time.monotonic()
    candidates = _cache

    # The process cache cannot authorize disclosure: another replica can commit
    # an opt-out, or a cache fill can finish after local invalidation. Query scalar
    # columns after the fill so neither cached names nor stale ORM instances can
    # bypass the authoritative database visibility check. DB errors fail closed.
    public_names = {
        user_id: _public_name(display_name, handle or "")
        for user_id, display_name, handle in session.exec(
            select(User.id, User.display_name, User.public_handle).where(  # type: ignore[call-overload]
                User.public_profile.is_(True)  # type: ignore[union-attr]
            )
        )
    }
    visible = [(uid, entry) for uid, entry in candidates if uid in public_names]
    # Keep every candidate in the cache: filtering an already-truncated top 50
    # would leave holes when users opt out. Copy to avoid mutating shared ranks.
    return [
        entry.model_copy(update={"rank": rank, "username": public_names[uid]})
        for rank, (uid, entry) in enumerate(visible[:50], start=1)
    ]


SUPPORTED_DISPLAY_CURRENCIES = frozenset({"USD", "EUR", "GBP", "JPY", "CAD", "INR"})


@router.get("/profile", response_model=ProfileOut)
def get_profile(session: SessionDep, user_id: UserIdDep) -> ProfileOut:
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    return _profile_out(session, user)


def _profile_out(session: Session, user: User) -> ProfileOut:
    assert user.id is not None
    return ProfileOut(
        user_id=user.id,
        public_profile=user.public_profile,
        display_currency=user.display_currency or "USD",
        public_handle=ensure_public_handle(session, user),
        display_name=user.display_name,
    )


@router.patch("/profile", response_model=ProfileOut)
def patch_profile(
    body: ProfilePatchIn,
    session: SessionDep,
    user_id: UserIdDep,
) -> ProfileOut:
    global _cache_ts

    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")

    if body.public_profile is not None:
        user.public_profile = body.public_profile
    if body.display_currency is not None:
        ccy = body.display_currency.upper()
        if ccy not in SUPPORTED_DISPLAY_CURRENCIES:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"Unsupported display_currency {ccy!r}; allowed: {sorted(SUPPORTED_DISPLAY_CURRENCIES)}",
            )
        user.display_currency = ccy
    if body.display_name is not None:
        user.display_name = body.display_name or None

    session.add(user)
    session.commit()
    if body.public_profile is not None or body.display_name is not None:
        _cache_ts = None  # Invalidate only after the change is durable.
    return _profile_out(session, user)
