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

from fastapi import APIRouter, Depends
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

# ``_cache_ts`` is the ``time.monotonic()`` reading when ``_cache`` was last
# built, or ``None`` when the cache has never been populated (or was
# invalidated). A ``None`` sentinel — rather than ``0.0`` — matters because
# ``time.monotonic()``'s zero point is arbitrary: on a freshly-booted host it
# can read below ``_CACHE_TTL``, so ``monotonic() - 0.0`` would wrongly look
# "fresh" and the endpoint would serve an empty leaderboard for the first hour
# after deploy.
_cache: list[LeaderboardEntryOut] = []
_cache_ts: float | None = None


def _build_leaderboard(session: Session) -> list[LeaderboardEntryOut]:
    public_users = list(
        session.exec(select(User).where(User.public_profile == True))  # noqa: E712
    )

    entries: list[tuple[float, Decimal, User]] = []
    for user in public_users:
        snapshots = list(
            session.exec(
                select(PortfolioSnapshot)
                .where(PortfolioSnapshot.user_id == user.id)
                .order_by(PortfolioSnapshot.date.asc())  # type: ignore[attr-defined]
            )
        )
        if snapshots:
            initial_nav = snapshots[0].nav
            current_nav = snapshots[-1].nav
        else:
            initial_nav = current_nav = _INITIAL_NAV

        return_pct = (
            float((current_nav - initial_nav) / initial_nav * 100) if initial_nav > 0 else 0.0
        )
        entries.append((return_pct, current_nav, user))

    entries.sort(key=lambda t: t[0], reverse=True)

    return [
        LeaderboardEntryOut(
            rank=rank,
            user_id=user.id,  # type: ignore[arg-type]
            username=user.name or user.email.split("@")[0],
            return_pct=round(return_pct, 4),
            portfolio_value=nav,
        )
        for rank, (return_pct, nav, user) in enumerate(entries[:50], start=1)
    ]


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
        from fastapi import HTTPException, status

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
    from fastapi import HTTPException, status

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
