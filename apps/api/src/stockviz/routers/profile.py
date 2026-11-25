"""`/v1/profile`: the caller's display settings.

GET   /v1/profile  - authed; the caller's display currency.
PATCH /v1/profile  - authed; sets it.

Until A0 this lived in the leaderboard router, with the public-profile flag
and the display name the leaderboard showed. The leaderboard is gone (A0
hygiene, workspace ``docs/stockviz-handover-2026-11-25.md``); the
``users.public_profile``, ``public_handle`` and ``display_name`` columns stay
in the database, unused.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session

from stockviz.auth import UserIdDep
from stockviz.db import get_session
from stockviz.models.user import User
from stockviz.schemas import ProfileOut, ProfilePatchIn

router = APIRouter(prefix="/v1", tags=["profile"])

SessionDep = Annotated[Session, Depends(get_session)]

SUPPORTED_DISPLAY_CURRENCIES = frozenset({"USD", "EUR", "GBP", "JPY", "CAD", "INR"})


def _user(session: Session, user_id: int) -> User:
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    return user


def _profile_out(user: User) -> ProfileOut:
    assert user.id is not None
    return ProfileOut(user_id=user.id, display_currency=user.display_currency or "USD")


@router.get("/profile", response_model=ProfileOut)
def get_profile(session: SessionDep, user_id: UserIdDep) -> ProfileOut:
    return _profile_out(_user(session, user_id))


@router.patch("/profile", response_model=ProfileOut)
def patch_profile(body: ProfilePatchIn, session: SessionDep, user_id: UserIdDep) -> ProfileOut:
    user = _user(session, user_id)
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
    session.refresh(user)
    return _profile_out(user)
