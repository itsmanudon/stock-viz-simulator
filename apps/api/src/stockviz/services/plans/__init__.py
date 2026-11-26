"""Trade plans (A5.4, M10.3): writing, linking, locking.

The rules (``models/trade_plan.py``):

- **Lock at the first fill.** ``record_fill`` is the one place a plan meets a
  fill. A plan that existed before the fill locks at the fill's time; one
  written after it is labelled ``written_after_entry`` and never locked.
  Either way the plan fields freeze (``TradePlan.frozen``).
- **Paper.** A buy placed with a plan (``trade_plan_id``, or a new plan on
  the ticket) links its fill in ``execute.apply_fill``; the plan's book must
  be the order's and the instrument the same. When a book's position in the
  instrument returns to zero, its active plans close.
- **Replay and drills.** One plan per replay session (``replay_session_id``),
  locked at the session's first replay fill: the A4.7 / SIM-07 rule, so the
  lock time is the simulated fill time. A plan started after the session's
  first fill (a replay journal opened late) is written after entry.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlmodel import Session, col, func, select

from stockviz._time import utcnow
from stockviz.models import (
    Instrument,
    Portfolio,
    ReplayFill,
    ReplaySession,
    Setup,
    SetupVersion,
    Thesis,
    Trade,
    TradeSide,
)
from stockviz.models.trade_plan import MAX_PLANS_PER_USER, TradePlan
from stockviz.schemas import TradePlanDraft, TradePlanOut, TradePlanPatch

# The fields the lock freezes. ``notes``, ``tags`` and ``status`` stay editable.
LOCKED_FIELDS = (
    "planned_entry",
    "planned_stop",
    "planned_target",
    "planned_size",
    "setup_version_id",
    "thesis_id",
    "thesis_text",
    "why",
    "invalidation",
    "horizon_bars",
    "confidence",
)
_MICROS = Decimal("0.000001")


class PlanError(Exception):
    """A plan the request cannot use (422)."""


class PlanNotFound(Exception):
    """No such plan for this user (404)."""


class PlanLocked(Exception):
    """The plan's fields froze at its first fill (409)."""


class PlanConflict(Exception):
    """The plan cannot take this change (409)."""


# --- the lock -------------------------------------------------------------------


def record_fill(plan: TradePlan, at: datetime, *, plan_predates_fill: bool | None = None) -> None:
    """The plan met a fill at ``at``. The first one locks it (or labels it).

    ``plan_predates_fill`` says whether the plan existed before the fill; by
    default ``created_at <= at`` (paper fills, whose time is wall time).
    Replay passes it, since a replay fill's time is the simulated bar's.
    """
    now = utcnow()
    if plan.first_fill_at is None or at < plan.first_fill_at:
        first = plan.first_fill_at is None
        plan.first_fill_at = at
        if first:
            before = plan.created_at <= at if plan_predates_fill is None else plan_predates_fill
            if before and not plan.written_after_entry:
                plan.locked_at = at
            else:
                plan.locked_at = None
                plan.written_after_entry = True
        elif plan.locked_at is not None:
            plan.locked_at = at
    if plan.status == "open":
        plan.status = "active"
    plan.updated_at = now


def apply_patch(plan: TradePlan, body: TradePlanPatch) -> None:
    """Edits: plan fields before the first fill only (else ``PlanLocked``)."""
    sent = body.model_fields_set
    changed = {
        name
        for name in LOCKED_FIELDS
        if name in sent and getattr(body, name) != getattr(plan, name)
    }
    if changed and plan.frozen:
        label = "written after entry" if plan.written_after_entry else "locked at its first fill"
        raise PlanLocked(
            f"The plan is {label}: its entry, stop, target, size, setup and thesis can no "
            "longer change. Notes and tags stay editable."
        )
    if changed and plan.status in ("closed", "cancelled"):
        raise PlanConflict(f"The plan is {plan.status}")
    for name in changed:
        setattr(plan, name, _clean(getattr(body, name)))
    if changed:
        _check_prices(plan)
    if "notes" in sent:
        plan.notes = _clean(body.notes)
    if "tags" in sent and body.tags is not None:
        plan.tags = clean_tags(body.tags)
    if body.status is not None:
        set_status(plan, body.status)
    plan.updated_at = utcnow()


def set_status(plan: TradePlan, status: str) -> None:
    if status == plan.status:
        return
    if status == "cancelled":
        if plan.status != "open":
            raise PlanConflict("Only a plan with no fill can be cancelled; close it instead")
    elif status == "closed" and plan.status != "active":
        raise PlanConflict("Only an active plan can be closed")
    plan.status = status


def _check_prices(plan: TradePlan) -> None:
    from stockviz.schemas import _check_plan_prices

    try:
        _check_plan_prices(plan.side, plan.planned_entry, plan.planned_stop, plan.planned_target)
    except ValueError as exc:
        raise PlanError(str(exc)) from exc


def _clean(value: Any) -> Any:
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


def clean_tags(tags: Iterable[str]) -> list[str]:
    """Trimmed, de-duplicated ignoring case, in the order given."""
    out: list[str] = []
    seen: set[str] = set()
    for tag in tags:
        t = " ".join(tag.split())
        if t and t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return out


# --- writing a paper plan -------------------------------------------------------


def check_references(
    session: Session, user_id: int, draft: TradePlanDraft | TradePlanPatch
) -> None:
    """The setup version must be yours or a preset's; the thesis yours."""
    from stockviz.services.setups import store

    if draft.setup_version_id is not None:
        try:
            store.visible_version(session, draft.setup_version_id, user_id)
        except store.SetupNotFound as exc:
            raise PlanNotFound(f"Setup version {draft.setup_version_id} not found") from exc
    if draft.thesis_id is not None:
        thesis = session.get(Thesis, draft.thesis_id)
        if thesis is None or thesis.user_id != user_id:
            raise PlanNotFound(f"Thesis {draft.thesis_id} not found")


def new_paper_plan(
    session: Session,
    *,
    user_id: int,
    book: Portfolio,
    instrument_id: int,
    draft: TradePlanDraft,
    source: str = "paper",
) -> TradePlan:
    """Stage a plan in ``book`` (not committed). Long only in a paper book:
    paper trading cannot sell short."""
    if draft.side == "short":
        raise PlanError("This book can't sell short, so its plans are long only")
    check_references(session, user_id, draft)
    if draft.thesis_id is not None:
        thesis = session.get(Thesis, draft.thesis_id)
        if thesis is not None and thesis.instrument_id != instrument_id:
            raise PlanError("The thesis is about another symbol")
    count = session.exec(
        select(func.count()).select_from(TradePlan).where(col(TradePlan.user_id) == user_id)
    ).one()
    if count >= MAX_PLANS_PER_USER:
        raise PlanConflict(f"At most {MAX_PLANS_PER_USER} plans")
    now = utcnow()
    assert book.id is not None
    plan = TradePlan(
        user_id=user_id,
        portfolio_id=book.id,
        instrument_id=instrument_id,
        source=source,
        side=draft.side,
        planned_entry=draft.planned_entry,
        planned_stop=draft.planned_stop,
        planned_target=draft.planned_target,
        planned_size=draft.planned_size,
        setup_version_id=draft.setup_version_id,
        thesis_id=draft.thesis_id,
        thesis_text=_clean(draft.thesis_text),
        why=_clean(draft.why),
        invalidation=_clean(draft.invalidation),
        horizon_bars=draft.horizon_bars,
        confidence=draft.confidence,
        notes=_clean(draft.notes),
        tags=clean_tags(draft.tags),
        status="open",
        created_at=now,
        updated_at=now,
    )
    session.add(plan)
    session.flush()
    return plan


def plan_for_order(
    session: Session,
    *,
    user_id: int,
    book: Portfolio,
    instrument_id: int,
    side: TradeSide,
    trade_plan_id: int | None,
    draft: TradePlanDraft | None,
) -> TradePlan | None:
    """The plan an order links to: an existing one, a new one, or none."""
    if trade_plan_id is None and draft is None:
        return None
    if trade_plan_id is not None and draft is not None:
        raise PlanError("Send trade_plan_id or plan, not both")
    if side != TradeSide.BUY:
        raise PlanError("A plan attaches to a buy: plans are long only here")
    if draft is not None:
        return new_paper_plan(
            session, user_id=user_id, book=book, instrument_id=instrument_id, draft=draft
        )
    assert trade_plan_id is not None
    plan = session.get(TradePlan, trade_plan_id)
    if plan is None or plan.user_id != user_id:
        raise PlanNotFound(f"Plan {trade_plan_id} not found")
    if plan.portfolio_id != book.id or plan.source != "paper":
        raise PlanError("The plan belongs to another book")
    if plan.instrument_id != instrument_id:
        raise PlanError("The plan is for another symbol")
    if plan.status not in ("open", "active"):
        raise PlanConflict(f"The plan is {plan.status}")
    return plan


def link_trade(session: Session, plan: TradePlan, trade: Trade) -> None:
    """Link a paper fill to its plan; the first fill locks it."""
    trade.trade_plan_id = plan.id
    record_fill(plan, trade.ts)
    session.add(trade)
    session.add(plan)


def close_flat_plans(session: Session, *, portfolio_id: int, instrument_id: int | None) -> None:
    """The book's position in the instrument is back to zero: its active plans close."""
    if instrument_id is None:
        return
    for plan in session.exec(
        select(TradePlan).where(
            col(TradePlan.portfolio_id) == portfolio_id,
            col(TradePlan.instrument_id) == instrument_id,
            col(TradePlan.status) == "active",
        )
    ):
        plan.status = "closed"
        plan.updated_at = utcnow()
        session.add(plan)


def open_position_entries(
    session: Session, *, portfolio_id: int, instrument_id: int
) -> list[Trade]:
    """The buys of the book's current position: every buy since its quantity
    last left zero. Empty when nothing is held."""
    trades = session.exec(
        select(Trade)
        .where(col(Trade.portfolio_id) == portfolio_id, col(Trade.instrument_id) == instrument_id)
        .order_by(col(Trade.ts), col(Trade.id))
    ).all()
    qty = Decimal(0)
    entries: list[Trade] = []
    for t in trades:
        if t.side == TradeSide.BUY:
            if qty == 0:
                entries = []
            qty += t.quantity
            entries.append(t)
        else:
            qty -= t.quantity
    return entries if qty > 0 else []


# --- replay and drill plans -----------------------------------------------------


def session_plan(session: Session, replay: ReplaySession) -> TradePlan | None:
    return session.exec(
        select(TradePlan).where(col(TradePlan.replay_session_id) == replay.id)
    ).first()


def first_replay_fill_at(session: Session, replay: ReplaySession) -> datetime | None:
    return session.exec(
        select(func.min(ReplayFill.evaluated_at)).where(col(ReplayFill.session_id) == replay.id)
    ).one()


def ensure_session_plan(session: Session, replay: ReplaySession, *, source: str) -> TradePlan:
    """The session's plan, staged empty if it has none (not committed).

    A plan started after the session's first fill is written after entry.
    """
    plan = session_plan(session, replay)
    if plan is not None:
        return plan
    assert replay.id is not None and replay.instrument_id is not None
    now = utcnow()
    plan = TradePlan(
        user_id=replay.user_id,
        replay_session_id=replay.id,
        instrument_id=replay.instrument_id,
        source=source,
        status="open",
        created_at=now,
        updated_at=now,
    )
    first = first_replay_fill_at(session, replay)
    if first is not None:
        record_fill(plan, first, plan_predates_fill=False)
    session.add(plan)
    session.flush()
    return plan


def sync_session_lock(session: Session, plan: TradePlan, replay: ReplaySession) -> bool:
    """Catch a plan up with a fill made before this read. True if it changed."""
    if plan.first_fill_at is not None:
        return False
    first = first_replay_fill_at(session, replay)
    if first is None:
        return False
    record_fill(plan, first, plan_predates_fill=True)
    session.add(plan)
    return True


def freeze_session_plan(session: Session, *, replay: ReplaySession, locked_at: datetime) -> None:
    """A replay fill at ``locked_at``: lock the session's plan (no-op without one)."""
    if replay.id is None:
        return
    plan = session_plan(session, replay)
    if plan is None or plan.first_fill_at is not None:
        return
    record_fill(plan, locked_at, plan_predates_fill=True)
    session.add(plan)


def end_session_plan(session: Session, *, replay: ReplaySession) -> None:
    """The session finished or was cancelled: an active plan closes, an
    unfilled one is cancelled."""
    plan = session_plan(session, replay)
    if plan is None:
        return
    if plan.status == "active":
        plan.status = "closed"
    elif plan.status == "open":
        plan.status = "cancelled"
    else:
        return
    plan.updated_at = utcnow()
    session.add(plan)


def hidden_drill_session_ids(session: Session, user_id: int) -> set[int]:
    """Replay sessions of anonymised drills not yet revealed (kept out of
    ``/v1/plans``: a plan names the real symbol and dates)."""
    from stockviz.models import Drill, DrillDeck

    rows = session.exec(
        select(Drill.session_id)
        .join(DrillDeck, col(DrillDeck.id) == col(Drill.deck_id))
        .where(
            col(DrillDeck.user_id) == user_id,
            col(DrillDeck.anonymised).is_(True),
            col(Drill.revealed_at).is_(None),
        )
    ).all()
    return set(rows)


# --- reading --------------------------------------------------------------------


def plan_outs(session: Session, plans: list[TradePlan]) -> list[TradePlanOut]:
    from stockviz.services.theses import tickers_for

    if not plans:
        return []
    instrument_ids = sorted({p.instrument_id for p in plans})
    tickers = tickers_for(session, instrument_ids)
    currencies = dict(
        session.exec(
            select(Instrument.id, Instrument.currency).where(col(Instrument.id).in_(instrument_ids))
        ).all()
    )
    version_ids = sorted({p.setup_version_id for p in plans if p.setup_version_id})
    labels: dict[int, str] = {}
    if version_ids:
        for vid, version, name in session.exec(
            select(SetupVersion.id, SetupVersion.version, Setup.name)
            .join(Setup, col(Setup.id) == col(SetupVersion.setup_id))
            .where(col(SetupVersion.id).in_(version_ids))
        ).all():
            assert vid is not None
            labels[vid] = f"{name} v{version}"
    thesis_ids = sorted({p.thesis_id for p in plans if p.thesis_id})
    titles: dict[int, str] = {}
    if thesis_ids:
        titles = {
            tid: title
            for tid, title in session.exec(
                select(Thesis.id, Thesis.title).where(col(Thesis.id).in_(thesis_ids))
            ).all()
            if tid is not None
        }
    plan_ids = [p.id for p in plans if p.id is not None]
    fills = dict(
        session.exec(
            select(Trade.trade_plan_id, func.count())
            .where(col(Trade.trade_plan_id).in_(plan_ids))
            .group_by(col(Trade.trade_plan_id))
        ).all()
    )
    return [
        plan_out(
            p,
            ticker=tickers.get(p.instrument_id),
            currency=currencies.get(p.instrument_id, "USD"),
            setup_label=labels.get(p.setup_version_id) if p.setup_version_id else None,
            thesis_title=titles.get(p.thesis_id) if p.thesis_id else None,
            fills=int(fills.get(p.id, 0)),
        )
        for p in plans
    ]


def plan_out(
    plan: TradePlan,
    *,
    ticker: str | None,
    currency: str,
    setup_label: str | None = None,
    thesis_title: str | None = None,
    fills: int = 0,
) -> TradePlanOut:
    assert plan.id is not None
    entry, stop, target, size = (
        plan.planned_entry,
        plan.planned_stop,
        plan.planned_target,
        plan.planned_size,
    )
    risk = abs(entry - stop) if entry is not None and stop is not None else None
    reward = abs(target - entry) if target is not None and entry is not None else None
    return TradePlanOut(
        id=plan.id,
        source=plan.source,  # pyright: ignore[reportArgumentType]
        book_id=plan.portfolio_id,
        replay_session_id=plan.replay_session_id,
        ticker=ticker,
        currency=currency,
        side=plan.side,  # pyright: ignore[reportArgumentType]
        planned_entry=entry,
        planned_stop=stop,
        planned_target=target,
        planned_size=size,
        risk_per_share=risk,
        planned_risk=(risk * size).quantize(_MICROS) if risk is not None and size else None,
        reward_per_share=reward,
        reward_risk=(reward / risk).quantize(Decimal("0.01"))
        if reward is not None and risk
        else None,
        setup_version_id=plan.setup_version_id,
        setup_label=setup_label,
        thesis_id=plan.thesis_id,
        thesis_title=thesis_title,
        thesis_text=plan.thesis_text,
        why=plan.why,
        invalidation=plan.invalidation,
        horizon_bars=plan.horizon_bars,
        confidence=plan.confidence,
        notes=plan.notes,
        tags=list(plan.tags or []),
        status=plan.status,  # pyright: ignore[reportArgumentType]
        locked=plan.locked_at is not None,
        locked_at=plan.locked_at,
        first_fill_at=plan.first_fill_at,
        written_after_entry=plan.written_after_entry,
        frozen=plan.frozen,
        fills=fills,
        created_at=plan.created_at,
        updated_at=plan.updated_at,
    )


__all__ = [
    "LOCKED_FIELDS",
    "PlanConflict",
    "PlanError",
    "PlanLocked",
    "PlanNotFound",
    "apply_patch",
    "check_references",
    "clean_tags",
    "close_flat_plans",
    "end_session_plan",
    "ensure_session_plan",
    "first_replay_fill_at",
    "freeze_session_plan",
    "hidden_drill_session_ids",
    "link_trade",
    "new_paper_plan",
    "open_position_entries",
    "plan_for_order",
    "plan_out",
    "plan_outs",
    "record_fill",
    "session_plan",
    "set_status",
    "sync_session_lock",
]
