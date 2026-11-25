"""`/v1/notifications/channels` — delivery beyond the bell (A2.3).

- ``GET``: the three channels (webhook, email, Telegram) with the user's
  settings, whether the server can send on each (``available``; email needs
  every ``SMTP_*`` value, Telegram ``TELEGRAM_BOT_TOKEN``) and the categories
  a channel can mute. The webhook secret is write-only: only ``secret_set``.
- ``PUT``: change one or more channels; fields left null are unchanged. A
  webhook URL must pass the SSRF rules that need no DNS (https; no private
  address literal; ``http://localhost`` outside production only); every
  send checks the resolved addresses again. Turning on a channel the server
  cannot send is 409; turning on one that is not filled in is 422.
- ``POST /{channel}/test``: sends a test message now through the same sender
  the nightly job uses (signing, address checks, timeouts). 409 when the
  server cannot send on it, 422 when it is not filled in; otherwise 200 with
  ``ok`` and what happened. At most ``TEST_LIMIT`` a minute per channel.
"""

from __future__ import annotations

import re
import threading
import time
from collections import deque
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlmodel import Session, select

from stockviz._time import utcnow
from stockviz.auth import UserIdDep
from stockviz.db import get_session
from stockviz.models import ChannelKind, NotificationCategory, NotificationChannel, User
from stockviz.schemas import (
    NotificationChannelIn,
    NotificationChannelOut,
    NotificationChannelsIn,
    NotificationChannelsOut,
    NotificationChannelTestOut,
)
from stockviz.services.delivery import DeliveryError, configured, send_test, server_available
from stockviz.services.delivery.channels import check_url_syntax

router = APIRouter(prefix="/v1/notifications/channels", tags=["notifications"])

SessionDep = Annotated[Session, Depends(get_session)]

CHANNELS = (ChannelKind.WEBHOOK, ChannelKind.EMAIL, ChannelKind.TELEGRAM)
CATEGORIES = [c.value for c in NotificationCategory]
MIN_SECRET = 16
TEST_LIMIT = 5
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_CHAT_ID = re.compile(r"^(-?\d{1,20}|@[A-Za-z0-9_]{5,32})$")

_tests: dict[tuple[int, str], deque[float]] = {}
_tests_lock = threading.Lock()


def _throttle(user_id: int, channel: str) -> None:
    now = time.monotonic()
    with _tests_lock:
        window = _tests.setdefault((user_id, channel), deque())
        while window and now - window[0] > 60:
            window.popleft()
        if len(window) >= TEST_LIMIT:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS, "Too many test sends; wait a minute"
            )
        window.append(now)


def _out(channel: str, row: NotificationChannel | None) -> NotificationChannelOut:
    cfg = (row.config if row else None) or {}
    return NotificationChannelOut(
        channel=channel,  # type: ignore[arg-type]
        enabled=bool(row and row.enabled),
        available=server_available(channel),
        configured=bool(row and configured(row)),
        url=cfg.get("url") if channel == ChannelKind.WEBHOOK else None,
        secret_set=bool(row and row.secret) if channel == ChannelKind.WEBHOOK else False,
        address=cfg.get("address") or None if channel == ChannelKind.EMAIL else None,
        chat_id=cfg.get("chat_id") if channel == ChannelKind.TELEGRAM else None,
        muted_categories=list(row.muted_categories or []) if row else [],
        updated_at=row.updated_at if row else None,
    )


def _rows(session: Session, user_id: int) -> dict[str, NotificationChannel]:
    rows = session.exec(
        select(NotificationChannel).where(NotificationChannel.user_id == user_id)
    ).all()
    return {r.channel: r for r in rows}


def _all(session: Session, user_id: int) -> NotificationChannelsOut:
    rows = _rows(session, user_id)
    return NotificationChannelsOut(
        channels=[_out(c.value, rows.get(c.value)) for c in CHANNELS], categories=CATEGORIES
    )


@router.get("", response_model=NotificationChannelsOut)
def list_channels(session: SessionDep, user_id: UserIdDep) -> NotificationChannelsOut:
    return _all(session, user_id)


def _apply(row: NotificationChannel, body: NotificationChannelIn) -> None:
    cfg = dict(row.config or {})
    if body.url is not None:
        url = body.url.strip()
        if row.channel != ChannelKind.WEBHOOK:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "url is for the webhook")
        if url:
            try:
                cfg["url"] = check_url_syntax(url)
            except DeliveryError as exc:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, exc.message) from exc
        else:
            cfg.pop("url", None)
    if body.secret is not None:
        if row.channel != ChannelKind.WEBHOOK:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "secret is for the webhook")
        secret = body.secret.strip()
        if secret and len(secret) < MIN_SECRET:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"the secret must be at least {MIN_SECRET} characters",
            )
        row.secret = secret or None
    if body.address is not None:
        if row.channel != ChannelKind.EMAIL:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "address is for email")
        address = body.address.strip()
        if address and not _EMAIL.match(address):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "not an email address")
        cfg["address"] = address
    if body.chat_id is not None:
        if row.channel != ChannelKind.TELEGRAM:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "chat_id is for Telegram")
        chat = body.chat_id.strip()
        if chat and not _CHAT_ID.match(chat):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "a chat id is a number (or @channelname)",
            )
        cfg["chat_id"] = chat
    if body.muted_categories is not None:
        unknown = sorted(set(body.muted_categories) - set(CATEGORIES))
        if unknown:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, f"unknown categories: {', '.join(unknown)}"
            )
        row.muted_categories = sorted(set(body.muted_categories))
    row.config = cfg
    if body.enabled is not None:
        if body.enabled and not server_available(row.channel):
            raise HTTPException(
                status.HTTP_409_CONFLICT, f"{row.channel} is not available on this server"
            )
        if body.enabled and not row.enabled:
            row.enabled_at = utcnow()
        row.enabled = body.enabled
    if row.enabled and not configured(row):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "the webhook needs a URL and a secret"
            if row.channel == ChannelKind.WEBHOOK
            else "Telegram needs a chat id",
        )
    row.updated_at = utcnow()


@router.put("", response_model=NotificationChannelsOut)
def put_channels(
    body: NotificationChannelsIn, session: SessionDep, user_id: UserIdDep
) -> NotificationChannelsOut:
    rows = _rows(session, user_id)
    for change in body.channels:
        row = rows.get(change.channel)
        if row is None:
            row = NotificationChannel(user_id=user_id, channel=change.channel)
            rows[change.channel] = row
        _apply(row, change)
        session.add(row)
    session.commit()
    return _all(session, user_id)


@router.post("/{channel}/test", response_model=NotificationChannelTestOut)
def test_channel(
    channel: Annotated[str, Path(pattern="^(webhook|email|telegram)$")],
    session: SessionDep,
    user_id: UserIdDep,
) -> NotificationChannelTestOut:
    if not server_available(channel):
        raise HTTPException(status.HTTP_409_CONFLICT, f"{channel} is not available on this server")
    row = _rows(session, user_id).get(channel)
    if row is None or not configured(row):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"set up {channel} before testing it"
        )
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    _throttle(user_id, channel)
    try:
        send_test(row, user)
    except DeliveryError as exc:
        return NotificationChannelTestOut(channel=channel, ok=False, detail=exc.message)  # type: ignore[arg-type]
    return NotificationChannelTestOut(channel=channel, ok=True, detail="sent")  # type: ignore[arg-type]
