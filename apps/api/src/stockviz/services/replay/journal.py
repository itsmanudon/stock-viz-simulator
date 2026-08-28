"""User-authored Replay journal with first-fill locking (SIM-07)."""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Session, select

from stockviz._time import utcnow
from stockviz.models import ReplayFill, ReplayJournal, ReplaySession
from stockviz.services.replay.errors import ReplayJournalLocked

_LOCKED_FIELDS = ("thesis", "invalidation", "expected_holding_bars", "confidence")


def _first_fill_at(session: Session, replay: ReplaySession) -> datetime | None:
    if replay.id is None:
        return None
    fills = list(session.exec(select(ReplayFill).where(ReplayFill.session_id == replay.id)).all())
    if not fills:
        return None
    fills.sort(key=lambda row: (row.evaluated_at, row.id or 0))
    return fills[0].evaluated_at


def get_replay_journal(session: Session, *, replay: ReplaySession) -> ReplayJournal:
    """Return the session journal, creating an empty row if needed.

    If fills already exist and ``locked_at`` is unset, freeze at the first fill.
    """

    assert replay.id is not None
    row = session.exec(
        select(ReplayJournal).where(ReplayJournal.session_id == replay.id).limit(1)
    ).first()
    first_fill_at = _first_fill_at(session, replay)
    now = utcnow()
    if row is None:
        row = ReplayJournal(
            session_id=replay.id,
            locked_at=first_fill_at,
            created_at=now,
            updated_at=now,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return row
    if row.locked_at is None and first_fill_at is not None:
        row.locked_at = first_fill_at
        row.updated_at = now
        session.add(row)
        session.commit()
        session.refresh(row)
    return row


def freeze_replay_journal(session: Session, *, replay: ReplaySession, locked_at: datetime) -> None:
    """Mark thesis fields immutable. No-op when no journal row exists yet."""

    if replay.id is None:
        return
    row = session.exec(
        select(ReplayJournal).where(ReplayJournal.session_id == replay.id).limit(1)
    ).first()
    if row is None or row.locked_at is not None:
        return
    row.locked_at = locked_at
    row.updated_at = utcnow()
    session.add(row)


def update_replay_journal(
    session: Session,
    *,
    replay: ReplaySession,
    thesis: str | None,
    invalidation: str | None,
    expected_holding_bars: int | None,
    confidence: int | None,
    reflection: str | None,
) -> ReplayJournal:
    row = get_replay_journal(session, replay=replay)
    locked = row.locked_at is not None or _first_fill_at(session, replay) is not None
    incoming = {
        "thesis": thesis,
        "invalidation": invalidation,
        "expected_holding_bars": expected_holding_bars,
        "confidence": confidence,
    }
    if locked:
        for name in _LOCKED_FIELDS:
            if getattr(row, name) != incoming[name]:
                raise ReplayJournalLocked(
                    "Thesis, invalidation, expected holding bars, and confidence "
                    "are locked after the first replay fill."
                )
        if row.locked_at is None:
            row.locked_at = _first_fill_at(session, replay)
    else:
        row.thesis = thesis
        row.invalidation = invalidation
        row.expected_holding_bars = expected_holding_bars
        row.confidence = confidence
    row.reflection = reflection
    row.updated_at = utcnow()
    session.add(row)
    session.commit()
    session.refresh(row)
    return row
