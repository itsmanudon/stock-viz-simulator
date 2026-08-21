"""`/v1/leaderboard` and `/v1/profile` — public rankings + opt-in visibility.

GET /v1/leaderboard  — public; returns top 50 users by return % who have
                       opted in. Result is cached in-process for one hour so
                       the endpoint is cheap to hit from the web app.

GET /v1/profile      — authed; returns the caller's public_profile flag.
PATCH /v1/profile    — authed; sets public_profile true/false.
"""

from __future__ import annotations

import time
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlmodel import Session, select

from stockviz.auth import UserIdDep
from stockviz.db import get_session
from stockviz.models import PortfolioSnapshot
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
_cache: list[LeaderboardEntryOut] = []
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


def _build_leaderboard(session: Session) -> list[LeaderboardEntryOut]:
    public_users = list(session.exec(select(User).where(User.public_profile.is_(True))))  # type: ignore[union-attr]
    navs_by_user = _first_and_last_navs(session, [u.id for u in public_users if u.id is not None])

    entries: list[tuple[float, Decimal, int, User]] = []
    for user in public_users:
        initial_nav, current_nav = navs_by_user.get(user.id or -1, (_INITIAL_NAV, _INITIAL_NAV))
        snapshot_count = _snapshot_counts(session).get(user.id or -1, 0)

        return_pct = (
            float((current_nav - initial_nav) / initial_nav * 100) if initial_nav > 0 else 0.0
        )
        entries.append((return_pct, current_nav, snapshot_count, user))

    # Users without a real track record can't be ranked meaningfully: a single
    # lucky day would otherwise top the board. They still appear, but below
    # everyone who has qualified.
    entries.sort(key=lambda t: (t[2] >= MIN_SNAPSHOTS_TO_RANK, t[0]), reverse=True)

    return [
        LeaderboardEntryOut(
            rank=rank,
            user_id=user.id,  # type: ignore[arg-type]
            username=user.name or user.email.split("@")[0],
            return_pct=round(return_pct, 4),
            portfolio_value=nav,
            days_tracked=snapshot_count,
            ranked=snapshot_count >= MIN_SNAPSHOTS_TO_RANK,
        )
        for rank, (return_pct, nav, snapshot_count, user) in enumerate(entries[:50], start=1)
    ]


def _snapshot_counts(session: Session) -> dict[int, int]:
    """Snapshots per user, cached for the life of one leaderboard build."""
    rows = session.exec(
        select(PortfolioSnapshot.user_id, func.count()).group_by(PortfolioSnapshot.user_id)  # type: ignore[call-overload]
    ).all()
    return dict(rows)


@router.get("/leaderboard", response_model=list[LeaderboardEntryOut])
def get_leaderboard(session: SessionDep) -> list[LeaderboardEntryOut]:
    global _cache, _cache_ts
    if _cache_ts is None or time.monotonic() - _cache_ts > _CACHE_TTL:
        _cache = _build_leaderboard(session)
        _cache_ts = time.monotonic()
    return _cache


SUPPORTED_DISPLAY_CURRENCIES = frozenset({"USD", "EUR", "GBP", "JPY", "CAD", "INR"})


@router.get("/profile", response_model=ProfileOut)
def get_profile(session: SessionDep, user_id: UserIdDep) -> ProfileOut:
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    return ProfileOut(
        user_id=user_id,
        public_profile=user.public_profile,
        display_currency=user.display_currency or "USD",
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
        _cache_ts = None  # public_profile flips invalidate the cache
    if body.display_currency is not None:
        ccy = body.display_currency.upper()
        if ccy not in SUPPORTED_DISPLAY_CURRENCIES:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"Unsupported display_currency {ccy!r}; allowed: {sorted(SUPPORTED_DISPLAY_CURRENCIES)}",
            )
        user.display_currency = ccy

    session.add(user)
    session.commit()
    return ProfileOut(
        user_id=user_id,
        public_profile=user.public_profile,
        display_currency=user.display_currency or "USD",
    )
