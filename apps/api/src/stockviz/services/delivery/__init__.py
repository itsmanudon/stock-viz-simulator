"""Notification delivery beyond the bell (A2.3, M4.5 end of day).

The outbox pattern (as ``events/outbox.py``, OP-12):

1. :func:`deliver` stages one ``delivery_attempts`` row per channel the user
   has enabled, that the server can send and whose muted categories do not
   include the notification's, **in the transaction that writes the
   notification** (``services/notifications.notify`` calls it). So a send
   exists exactly when its notification commits, and never before.
2. :func:`drain` (the ``deliver-notifications`` job, after the night's
   notifying steps; also run by hand) sends due rows after commit, one row
   per transaction, the row locked (``FOR UPDATE SKIP LOCKED`` on
   PostgreSQL) so two drains never send one row twice.
3. Retry: a retryable failure waits ``BACKOFF_SECONDS[attempts - 1]``
   (1 min, 5 min, 30 min, 2 h, 6 h); after ``MAX_ATTEMPTS`` (6), or on a
   permanent error (a refused address, a redirect, a 4xx), the row is
   ``dead`` with ``dead_at`` and its last error. A row whose channel was
   turned off, or whose server config is gone, is ``skipped``.
4. Idempotent: unique (notification, channel), so a rerun stages nothing
   new, and a sent row is never sent again.

The receiver should de-duplicate on the payload's ``id`` (a send that timed
out after the receiver got it is retried).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlmodel import Session, col, select

from stockviz import _time
from stockviz.models import (
    ChannelKind,
    DeliveryAttempt,
    DeliveryStatus,
    Notification,
    NotificationChannel,
    User,
)
from stockviz.services.delivery.channels import (
    DeliveryError,
    send_email,
    send_telegram,
    send_webhook,
)
from stockviz.settings import get_settings

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 6
BACKOFF_SECONDS = (60, 300, 1800, 7200, 21600)
DRAIN_LIMIT = 500


def server_available(channel: str) -> bool:
    """Whether this server can send on ``channel`` (email and Telegram need keys)."""
    s = get_settings()
    if channel == ChannelKind.WEBHOOK:
        return True
    if channel == ChannelKind.EMAIL:
        return s.email_configured
    if channel == ChannelKind.TELEGRAM:
        return s.telegram_configured
    return False


def configured(row: NotificationChannel) -> bool:
    """The user's part of the settings is filled in."""
    cfg = row.config or {}
    if row.channel == ChannelKind.WEBHOOK:
        return bool(cfg.get("url")) and bool(row.secret)
    if row.channel == ChannelKind.TELEGRAM:
        return bool(cfg.get("chat_id"))
    return row.channel == ChannelKind.EMAIL  # blank address = the account email


def payload(n: Notification) -> dict[str, Any]:
    """What a webhook receives (the same fields every channel words)."""
    return {
        "id": n.id,
        "category": n.category,
        "title": n.title,
        "body": n.body,
        "created_at": n.created_at.isoformat() if n.created_at else None,
        "data": n.data,
    }


def deliver(session: Session, notification: Notification) -> list[DeliveryAttempt]:
    """Stage a send per enabled channel. In the caller's transaction; no commit."""
    channels = session.exec(
        select(NotificationChannel).where(
            NotificationChannel.user_id == notification.user_id,
            col(NotificationChannel.enabled).is_(True),
        )
    ).all()
    wanted = [
        c
        for c in channels
        if server_available(c.channel)
        and configured(c)
        and notification.category not in (c.muted_categories or [])
    ]
    if not wanted:
        return []
    if notification.id is None:
        session.flush()
    assert notification.id is not None
    staged = []
    for c in wanted:
        exists = session.exec(
            select(DeliveryAttempt.id).where(
                DeliveryAttempt.notification_id == notification.id,
                DeliveryAttempt.channel == c.channel,
            )
        ).first()
        if exists is not None:
            continue
        row = DeliveryAttempt(
            notification_id=notification.id,
            user_id=notification.user_id,
            channel=c.channel,
            next_attempt_at=_time.utcnow(),
        )
        session.add(row)
        staged.append(row)
    return staged


def _text(n: dict[str, Any]) -> str:
    lines = [str(n.get("title") or ""), "", str(n.get("body") or "")]
    data = n.get("data") or {}
    for label, key in (("Entered", "entries"), ("Left", "exits")):
        items = data.get(key) if isinstance(data, dict) else None
        if items:
            lines.append(f"{label}: {', '.join(str(i) for i in items)}")
    return "\n".join(lines).strip()


def send(channel: NotificationChannel, user: User, body: dict[str, Any]) -> None:
    """Send ``body`` on ``channel``. Raises :class:`DeliveryError`."""
    if not server_available(channel.channel):
        raise DeliveryError(f"{channel.channel} is not available on this server", retryable=False)
    cfg = channel.config or {}
    if channel.channel == ChannelKind.WEBHOOK:
        send_webhook(str(cfg.get("url") or ""), channel.secret or "", body)
    elif channel.channel == ChannelKind.EMAIL:
        to = str(cfg.get("address") or "").strip() or user.email
        send_email(to, f"StockViz: {body.get('title') or 'notification'}"[:200], _text(body))
    elif channel.channel == ChannelKind.TELEGRAM:
        chat = str(cfg.get("chat_id") or "").strip()
        if not chat:
            raise DeliveryError("no Telegram chat id is set", retryable=False)
        send_telegram(chat, _text(body))
    else:
        raise DeliveryError(f"unknown channel {channel.channel!r}", retryable=False)


@dataclass
class DrainResult:
    sent: int = 0
    retrying: int = 0
    dead: int = 0
    skipped: int = 0
    by_channel: dict[str, int] = field(default_factory=dict)


def _claim(session: Session, attempt_id: int, now: datetime) -> DeliveryAttempt | None:
    stmt = select(DeliveryAttempt).where(
        DeliveryAttempt.id == attempt_id,
        DeliveryAttempt.status == DeliveryStatus.PENDING.value,
        col(DeliveryAttempt.next_attempt_at) <= now,
    )
    if session.get_bind().dialect.name == "postgresql":
        stmt = stmt.with_for_update(skip_locked=True)
    return session.exec(stmt).first()


def drain(
    session: Session,
    *,
    now: datetime | None = None,
    limit: int = DRAIN_LIMIT,
    channel: str | None = None,
) -> DrainResult:
    """Send every due pending row, oldest first. Commits after each row."""
    now = now or _time.utcnow()
    stmt = select(DeliveryAttempt.id).where(
        DeliveryAttempt.status == DeliveryStatus.PENDING.value,
        col(DeliveryAttempt.next_attempt_at) <= now,
    )
    if channel is not None:
        stmt = stmt.where(DeliveryAttempt.channel == channel)
    ids = list(session.exec(stmt.order_by(col(DeliveryAttempt.id)).limit(limit)).all())
    result = DrainResult()
    for attempt_id in ids:
        if attempt_id is None:
            continue
        row = _claim(session, attempt_id, now)
        if row is None:
            session.rollback()
            continue
        chan = session.exec(
            select(NotificationChannel).where(
                NotificationChannel.user_id == row.user_id,
                NotificationChannel.channel == row.channel,
            )
        ).first()
        notification = session.get(Notification, row.notification_id)
        user = session.get(User, row.user_id)
        if (
            chan is None
            or not chan.enabled
            or not configured(chan)
            or not server_available(chan.channel)
            or notification is None
            or user is None
            or notification.category in (chan.muted_categories or [])
        ):
            row.status = DeliveryStatus.SKIPPED.value
            row.last_error = "the channel is off"
            result.skipped += 1
        else:
            row.attempts += 1
            try:
                send(chan, user, payload(notification))
            except DeliveryError as exc:
                row.last_error = exc.message[:500]
                if not exc.retryable or row.attempts >= MAX_ATTEMPTS:
                    row.status = DeliveryStatus.DEAD.value
                    row.dead_at = now
                    result.dead += 1
                else:
                    wait = BACKOFF_SECONDS[min(row.attempts, len(BACKOFF_SECONDS)) - 1]
                    row.next_attempt_at = now + timedelta(seconds=wait)
                    result.retrying += 1
                logger.warning(
                    "delivery %s (%s) attempt %s failed: %s",
                    row.id, row.channel, row.attempts, row.last_error,
                )  # fmt: skip
            else:
                row.status = DeliveryStatus.SENT.value
                row.sent_at = now
                row.last_error = None
                result.sent += 1
                result.by_channel[row.channel] = result.by_channel.get(row.channel, 0) + 1
        session.add(row)
        session.commit()
    return result


def send_test(channel: NotificationChannel, user: User) -> None:
    """A test message through the real sender (signing, SSRF checks, transport)."""
    send(
        channel,
        user,
        {
            "id": 0,
            "category": "system",
            "title": "StockViz test notification",
            "body": f"Your {channel.channel} channel works.",
            "created_at": _time.utcnow().isoformat(),
            "data": {"test": True},
        },
    )


__all__ = [
    "BACKOFF_SECONDS",
    "MAX_ATTEMPTS",
    "DeliveryError",
    "DrainResult",
    "configured",
    "deliver",
    "drain",
    "payload",
    "send",
    "send_test",
    "server_available",
]
