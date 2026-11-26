"""User-authored Replay journal with first-fill locking (SIM-07).

Since A5.4 the journal is the session's trade plan (``trade_plans``, keyed on
the replay session; ``services/plans``): thesis -> ``thesis_text``,
expected holding bars -> ``horizon_bars``, reflection -> ``notes``. The rule
is unchanged: thesis, invalidation, expected holding bars and confidence
freeze at the first replay fill; reflection stays editable. A journal
started after the first fill is "written after entry", frozen the same way.
"""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Session, col, select

from stockviz._time import utcnow
from stockviz.models import Drill, ReplaySession
from stockviz.models.trade_plan import TradePlan
from stockviz.services import plans
from stockviz.services.replay.errors import ReplayJournalLocked

# journal field -> plan column
_LOCKED_FIELDS = {
    "thesis": "thesis_text",
    "invalidation": "invalidation",
    "expected_holding_bars": "horizon_bars",
    "confidence": "confidence",
}


def session_source(session: Session, replay: ReplaySession) -> str:
    """``drill`` for a drill's session, else ``replay``."""
    found = session.exec(select(Drill.id).where(col(Drill.session_id) == replay.id)).first()
    return "drill" if found is not None else "replay"


def get_replay_journal(session: Session, *, replay: ReplaySession) -> TradePlan:
    """Return the session's plan, creating an empty one if needed.

    If fills already exist and the plan has not seen one, catch it up: a
    plan that existed before the fill locks at it.
    """

    assert replay.id is not None
    plan = plans.session_plan(session, replay)
    if plan is None:
        plan = plans.ensure_session_plan(session, replay, source=session_source(session, replay))
        session.commit()
        session.refresh(plan)
        return plan
    if plans.sync_session_lock(session, plan, replay):
        session.commit()
        session.refresh(plan)
    return plan


def freeze_replay_journal(session: Session, *, replay: ReplaySession, locked_at: datetime) -> None:
    """Mark thesis fields immutable. No-op when no plan exists yet."""

    plans.freeze_session_plan(session, replay=replay, locked_at=locked_at)


def update_replay_journal(
    session: Session,
    *,
    replay: ReplaySession,
    thesis: str | None,
    invalidation: str | None,
    expected_holding_bars: int | None,
    confidence: int | None,
    reflection: str | None,
) -> TradePlan:
    plan = get_replay_journal(session, replay=replay)
    incoming = {
        "thesis": thesis,
        "invalidation": invalidation,
        "expected_holding_bars": expected_holding_bars,
        "confidence": confidence,
    }
    if plan.frozen or plans.first_replay_fill_at(session, replay) is not None:
        for name, column in _LOCKED_FIELDS.items():
            if getattr(plan, column) != incoming[name]:
                raise ReplayJournalLocked(
                    "Thesis, invalidation, expected holding bars, and confidence "
                    "are locked after the first replay fill."
                )
        plans.sync_session_lock(session, plan, replay)
    else:
        for name, column in _LOCKED_FIELDS.items():
            setattr(plan, column, incoming[name])
    plan.notes = reflection
    plan.updated_at = utcnow()
    session.add(plan)
    session.commit()
    session.refresh(plan)
    return plan
