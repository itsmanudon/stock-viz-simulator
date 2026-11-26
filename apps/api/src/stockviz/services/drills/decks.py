"""Decks, drills and plans (A4.7, M9.3): creating, reading, revealing.

See ``models/drill.py`` for the tables, ``triggers.py`` for how triggers are
found and sampled, ``anonymise.py`` for what an anonymised drill hides and
``score.py`` for the process score.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlmodel import Session, col, func, select

from stockviz import _time
from stockviz.models import (
    Drill,
    DrillDeck,
    DrillPlan,
    PriceBar,
    ReplayFill,
    ReplaySession,
    ReplaySessionStatus,
    Symbol,
)
from stockviz.models.drill import MAX_DECKS_PER_USER
from stockviz.schemas import (
    DrillDeckIn,
    DrillDeckOut,
    DrillDeckSummaryOut,
    DrillPlanIn,
    DrillPlanOut,
    DrillRevealHorizonOut,
    DrillRowOut,
    DrillRuleOut,
    DrillScoreOut,
)
from stockviz.services.backtest.strategy_run import _resolve_rule, inline_rule_version
from stockviz.services.checklist.evidence import WINDOW_YEARS
from stockviz.services.drills.anonymise import Mask, label_for
from stockviz.services.drills.score import BarFacts, FillFacts, PlanFacts, score_drill
from stockviz.services.drills.triggers import draw, find_triggers, offset_weeks
from stockviz.services.dsl import load_symbol
from stockviz.services.instruments import instrument_of
from stockviz.services.markets.calendar import latest_completed_session, venue_for_ticker
from stockviz.services.replay import (
    cancel_replay_session,
    compute_replay_summary,
    create_replay_session,
    get_visible_replay_history,
    list_replay_fills,
)
from stockviz.services.scan_event_study import resolve_universe

INLINE_SETUP_NAME = "Rules from drills"
"""The setup holding a user's inline drill rules, one version each."""
REVEAL_HORIZONS = (5, 20, 60)
NEXT_BARS = 60

METHOD = {
    "triggers": (
        "Every session where the rule turned true after being false (vector mode, the scan "
        "event study's definition; a session after an unknown one is not a trigger), on "
        "every symbol of the universe in the date range. No cooldown."
    ),
    "sampling": (
        "K triggers drawn at random without replacement from the eligible ones (sorted by "
        "date, then ticker) with the deck's seed; with K at least the eligible count, the "
        "deck holds them all."
    ),
    "session": (
        "Each drill is a replay session that opens at the trigger bar with N stored bars of "
        "lead-in visible, and ends M bars after the trigger (clamped to the stored bars)."
    ),
    "lag": (
        "NSE/BSE triggers whose session would end within 30 days of today are skipped and "
        "counted (the replay lag)."
    ),
    "anonymised": (
        "The symbol shows as Stock A, B, C... by position; company, sector and headlines are "
        "hidden; every date is shifted by a whole number of weeks (52 to 520, earlier or "
        "later), so weekdays are real; prices and returns are unchanged. All is revealed at "
        "the end."
    ),
    "score": (
        "Process, not profit: entry within 2% of the plan, the stop honoured, size within "
        "the plan. R achieved is shown separately and is not the score. No ranking."
    ),
}


class DrillError(ValueError):
    """A 400."""


class DrillNotFound(LookupError):
    """A 404 (another user's deck or drill too)."""


class DrillConflict(RuntimeError):
    """A 409."""


@dataclass(frozen=True)
class DrillContext:
    drill: Drill
    deck: DrillDeck
    replay: ReplaySession

    @property
    def masked(self) -> bool:
        return self.deck.anonymised and self.drill.revealed_at is None


# --- creation ----------------------------------------------------------------


def create_deck(
    session: Session,
    body: DrillDeckIn,
    *,
    user_id: int,
    now: datetime | None = None,
    today: date | None = None,
) -> DrillDeck:
    """Raises the strategy loaders' errors (404/401/422), ``ScanStudyError`` /
    ``DrillError`` (400) and ``DrillConflict`` (409, too many decks)."""
    count = session.exec(
        select(func.count()).select_from(DrillDeck).where(col(DrillDeck.user_id) == user_id)
    ).one()
    if count >= MAX_DECKS_PER_USER:
        raise DrillConflict(f"At most {MAX_DECKS_PER_USER} decks; delete one first")
    rule = _resolve_rule(session, body.rule, "trigger", user_id)
    tickers, source = resolve_universe(session, body.universe, user_id)
    now = now or _time.utcnow()
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    end = body.to or latest_completed_session(now, venue_for_ticker(tickers[0]))
    start = body.from_ or end - timedelta(days=365 * WINDOW_YEARS)
    if start > end:
        raise DrillError("'from' must be on or before 'to'")
    compiled = rule.compiled
    lookback = None if compiled.lookback is None else compiled.lookback + 1
    datasets = [
        load_symbol(
            session,
            t,
            end=end,
            start=start,
            lookback=lookback,
            needs=compiled.needs,
            user_id=user_id,
        )
        for t in tickers
    ]
    triggers = find_triggers(datasets, compiled, start=start, end=end)
    seed = body.seed if body.seed is not None else secrets.randbelow(2**31)
    result = draw(
        session, triggers, k=body.k, lead_bars=body.lead_bars, follow_bars=body.follow_bars,
        seed=seed, user_id=user_id, today=today,
    )  # fmt: skip
    if not result.chosen:
        raise DrillError(
            f"No eligible triggers: the rule turned true {len(triggers)} times in the range"
            + (f" ({result.lag_skipped} inside the 30-day lag)" if result.lag_skipped else "")
        )
    version_id = rule.version_id
    if version_id is None:
        version = inline_rule_version(
            session,
            user_id,
            compiled,
            name=INLINE_SETUP_NAME,
            kind="screen",
            description="Inline rules from drill decks; one version per rule.",
        )
        version_id = version.id
    assert version_id is not None
    name = body.name.strip() if body.name and body.name.strip() else None
    deck = DrillDeck(
        user_id=user_id,
        name=name or f"{compiled.canonical_text[:80]} · {source.name or source.kind}",
        setup_version_id=version_id,
        rule_text=compiled.text,
        rule_hash=compiled.hash,
        universe={
            **body.universe.model_dump(exclude_none=True),
            **{f"source_{k}": v for k, v in source.model_dump(exclude_none=True).items()},
        },
        from_date=start,
        to_date=end,
        k=body.k,
        lead_bars=body.lead_bars,
        follow_bars=body.follow_bars,
        seed=seed,
        anonymised=body.anonymised,
        triggers_found=len(triggers),
        triggers_eligible=len(result.eligible),
        lag_skipped=result.lag_skipped,
    )
    session.add(deck)
    session.flush()
    assert deck.id is not None
    today_d = today or now.date()
    drills: list[Drill] = []
    for position, window in enumerate(result.chosen):
        replay = create_replay_session(
            session,
            user_id=user_id,
            ticker=window.trigger.ticker,
            start_at=window.start_at,
            end_at=window.end_at,
            today=today,
        )
        replay.current_at = window.trigger_at
        session.add(replay)
        assert replay.id is not None
        weeks_ahead = (today_d - window.end_at.date()).days // 7
        offset = offset_weeks(seed, position, shown_end_limit=weeks_ahead) if deck.anonymised else 0
        drill = Drill(
            deck_id=deck.id,
            position=position,
            session_id=replay.id,
            ticker=window.trigger.ticker,
            trigger_at=window.trigger_at,
            trigger_date=window.trigger.day,
            date_offset_weeks=offset,
        )
        session.add(drill)
        drills.append(drill)
    session.commit()
    session.refresh(deck)
    return deck


# --- reads -------------------------------------------------------------------


def owned_deck(session: Session, deck_id: int, user_id: int) -> DrillDeck:
    deck = session.get(DrillDeck, deck_id)
    if deck is None or deck.user_id != user_id:
        raise DrillNotFound(f"Deck {deck_id} not found")
    return deck


def deck_drills(session: Session, deck: DrillDeck) -> list[Drill]:
    return list(
        session.exec(
            select(Drill).where(col(Drill.deck_id) == deck.id).order_by(col(Drill.position))
        ).all()
    )


def list_decks(session: Session, user_id: int) -> list[DrillDeck]:
    return list(
        session.exec(
            select(DrillDeck)
            .where(col(DrillDeck.user_id) == user_id)
            .order_by(col(DrillDeck.id).desc())
        ).all()
    )


def load_drill(session: Session, drill_id: int, user_id: int) -> DrillContext:
    drill = session.get(Drill, drill_id)
    if drill is None:
        raise DrillNotFound(f"Drill {drill_id} not found")
    deck = session.get(DrillDeck, drill.deck_id)
    replay = session.get(ReplaySession, drill.session_id)
    if deck is None or replay is None or deck.user_id != user_id or replay.user_id != user_id:
        raise DrillNotFound(f"Drill {drill_id} not found")
    return DrillContext(drill, deck, replay)


def mask_for(session: Session, ctx: DrillContext) -> Mask | None:
    if not ctx.masked:
        return None
    symbol = session.get(Symbol, ctx.drill.ticker)
    names = tuple(n for n in ((symbol.name if symbol else None),) if n)
    return Mask(
        ticker=ctx.drill.ticker,
        label=label_for(ctx.drill.position),
        offset_weeks=ctx.drill.date_offset_weeks,
        names=names,
    )


def is_hidden_session(session: Session, session_id: int) -> bool:
    """True for an anonymised, unrevealed drill's replay session (``/v1/replay``
    answers 404 for it)."""
    row = session.exec(
        select(Drill.id)
        .join(DrillDeck, col(DrillDeck.id) == col(Drill.deck_id))
        .where(
            col(Drill.session_id) == session_id,
            col(DrillDeck.anonymised),
            col(Drill.revealed_at).is_(None),
        )
    ).first()
    return row is not None


def drill_session_ids(session: Session, user_id: int) -> set[int]:
    """Every drill session of the user (kept out of the ``/replay`` list)."""
    rows = session.exec(
        select(Drill.session_id)
        .join(DrillDeck, col(DrillDeck.id) == col(Drill.deck_id))
        .where(col(DrillDeck.user_id) == user_id)
    ).all()
    return set(rows)


def plan_of(session: Session, replay: ReplaySession) -> DrillPlan | None:
    return session.exec(select(DrillPlan).where(col(DrillPlan.session_id) == replay.id)).first()


def _first_fill_at(session: Session, replay: ReplaySession) -> datetime | None:
    return session.exec(
        select(func.min(ReplayFill.evaluated_at)).where(col(ReplayFill.session_id) == replay.id)
    ).one()


def status_of(session: Session, ctx: DrillContext, plan: DrillPlan | None) -> str:
    if ctx.drill.revealed_at is not None:
        return "revealed"
    r = ctx.replay
    if (
        plan is not None
        or r.status != ReplaySessionStatus.ACTIVE.value
        or r.current_at != ctx.drill.trigger_at
        or _first_fill_at(session, r) is not None
    ):
        return "in_progress"
    return "not_started"


def plan_out(session: Session, ctx: DrillContext, plan: DrillPlan) -> DrillPlanOut:
    first = _first_fill_at(session, ctx.replay)
    if first is not None and plan.locked_at is None:
        plan.locked_at = first
        session.add(plan)
        session.commit()
        session.refresh(plan)
    return DrillPlanOut(
        planned_entry=plan.planned_entry,
        planned_stop=plan.planned_stop,
        planned_size=plan.planned_size,
        planned_risk=((plan.planned_entry - plan.planned_stop) * plan.planned_size).quantize(
            Decimal("0.000001")
        ),
        note=plan.note,
        locked=plan.locked_at is not None,
        locked_at=plan.locked_at,
    )


def score_of(session: Session, ctx: DrillContext, plan: DrillPlan | None) -> DrillScoreOut | None:
    """The process score, once revealed (null before, or without a plan)."""
    if ctx.drill.revealed_at is None or plan is None:
        return None
    fills = [
        FillFacts(f.side, f.quantity, f.fill_price, f.evaluated_at)
        for f in list_replay_fills(session, replay=ctx.replay)
    ]
    bars = [BarFacts(b.ts, b.close) for b in get_visible_replay_history(session, ctx.replay)]
    summary = compute_replay_summary(session, ctx.replay)
    return score_drill(
        PlanFacts(plan.planned_entry, plan.planned_stop, plan.planned_size),
        fills,
        bars,
        total_pnl=summary.total_pnl,
    )


def deck_out(session: Session, deck: DrillDeck) -> DrillDeckOut:
    assert deck.id is not None
    rows: list[DrillRowOut] = []
    counts = {"not_started": 0, "in_progress": 0, "revealed": 0}
    traded = followed = passed = applicable = 0
    for drill in deck_drills(session, deck):
        replay = session.get(ReplaySession, drill.session_id)
        assert replay is not None and drill.id is not None
        ctx = DrillContext(drill, deck, replay)
        plan = plan_of(session, replay)
        status = status_of(session, ctx, plan)
        counts[status] += 1
        score = score_of(session, ctx, plan)
        if score is not None:
            traded += int(score.traded)
            followed += int(bool(score.followed_plan))
            passed += score.passed
            applicable += score.applicable
        rows.append(
            DrillRowOut(
                id=drill.id,
                position=drill.position,
                label=label_for(drill.position) if ctx.masked else drill.ticker,
                status=status,  # pyright: ignore[reportArgumentType]
                ticker=None if ctx.masked else drill.ticker,
                trigger_date=None if ctx.masked else drill.trigger_date,
                score=score,
            )
        )
    version_rule = DrillRuleOut(
        text=deck.rule_text,
        canonical=_canonical(session, deck),
        hash=deck.rule_hash,
        setup_version_id=deck.setup_version_id,
    )
    return DrillDeckOut(
        id=deck.id,
        name=deck.name,
        rule=version_rule,
        universe=dict(deck.universe),
        **{"from": deck.from_date},
        to=deck.to_date,
        k=deck.k,
        lead_bars=deck.lead_bars,
        follow_bars=deck.follow_bars,
        seed=deck.seed,
        anonymised=deck.anonymised,
        triggers_found=deck.triggers_found,
        triggers_eligible=deck.triggers_eligible,
        lag_skipped=deck.lag_skipped,
        created_at=deck.created_at,
        drills=rows,
        summary=DrillDeckSummaryOut(
            drills=len(rows),
            traded=traded,
            followed_plan=followed,
            checks_passed=passed,
            checks_applicable=applicable,
            **counts,
        ),
        method=METHOD,
    )


def _canonical(session: Session, deck: DrillDeck) -> str:
    from stockviz.models import SetupVersion

    version = session.get(SetupVersion, deck.setup_version_id)
    return version.canonical_text if version is not None else deck.rule_text


def delete_deck(session: Session, deck: DrillDeck) -> None:
    """The deck, its drills, their plans and their replay sessions."""
    drills = deck_drills(session, deck)
    session_ids = [d.session_id for d in drills]
    for plan in session.exec(select(DrillPlan).where(col(DrillPlan.session_id).in_(session_ids))):
        session.delete(plan)
    for drill in drills:
        session.delete(drill)
    session.flush()
    session.delete(deck)
    session.flush()
    from stockviz.models import (
        ReplayDrawing,
        ReplayJournal,
        ReplayOrder,
        ReplayPosition,
    )

    # The database cascades these on PostgreSQL; deleting them here keeps
    # SQLite (no enforced foreign keys) the same.
    for model in (ReplayFill, ReplayOrder, ReplayPosition, ReplayDrawing, ReplayJournal):
        for child in session.exec(
            select(model).where(col(model.session_id).in_(session_ids))  # pyright: ignore[reportAttributeAccessIssue]
        ):
            session.delete(child)
    session.flush()
    for sid in session_ids:
        row = session.get(ReplaySession, sid)
        if row is not None:
            session.delete(row)
    session.commit()


# --- plan and reveal -----------------------------------------------------------


def put_plan(session: Session, ctx: DrillContext, body: DrillPlanIn) -> DrillPlan:
    if ctx.drill.revealed_at is not None:
        raise DrillConflict("The drill is revealed; its plan is final")
    plan = plan_of(session, ctx.replay)
    if _first_fill_at(session, ctx.replay) is not None:
        raise DrillConflict("The plan locked at the first fill")
    now = _time.utcnow()
    if plan is None:
        assert ctx.replay.id is not None
        plan = DrillPlan(
            session_id=ctx.replay.id,
            planned_entry=body.planned_entry,
            planned_stop=body.planned_stop,
            planned_size=body.planned_size,
            note=body.note.strip() if body.note and body.note.strip() else None,
            created_at=now,
            updated_at=now,
        )
    else:
        plan.planned_entry = body.planned_entry
        plan.planned_stop = body.planned_stop
        plan.planned_size = body.planned_size
        plan.note = body.note.strip() if body.note and body.note.strip() else None
        plan.updated_at = now
    session.add(plan)
    session.commit()
    session.refresh(plan)
    return plan


def require_plan(session: Session, ctx: DrillContext) -> None:
    if plan_of(session, ctx.replay) is None:
        raise DrillConflict("Write your plan (planned entry, stop and size) before the first order")


def reveal(session: Session, ctx: DrillContext) -> DrillContext:
    """Ends the session if it is still running (cancelled: read-only) and
    reveals the drill. Idempotent."""
    if ctx.drill.revealed_at is not None:
        return ctx
    replay = ctx.replay
    if replay.status == ReplaySessionStatus.ACTIVE.value:
        replay = cancel_replay_session(session, replay=replay)
    ctx.drill.revealed_at = _time.utcnow()
    session.add(ctx.drill)
    session.commit()
    session.refresh(ctx.drill)
    return DrillContext(ctx.drill, ctx.deck, replay)


def after_trigger(
    session: Session, ctx: DrillContext
) -> tuple[list[DrillRevealHorizonOut], list[PriceBar]]:
    """Forward returns from the trigger's close and the bars after the session."""
    rows = list(
        session.exec(
            select(PriceBar)
            .where(
                PriceBar.instrument_id == instrument_of(ctx.drill.ticker),
                PriceBar.interval == "1d",
                col(PriceBar.ts) >= ctx.drill.trigger_at,
            )
            .order_by(col(PriceBar.ts))
            .limit(max(REVEAL_HORIZONS) + 1)
        ).all()
    )
    venue = venue_for_ticker(ctx.drill.ticker)
    from stockviz.services.bars.resample import bar_date

    base = rows[0].close if rows else None
    out = []
    for h in REVEAL_HORIZONS:
        if base is not None and len(rows) > h and base > 0:
            row = rows[h]
            out.append(
                DrillRevealHorizonOut(
                    bars=h,
                    date=bar_date(row.ts, venue),
                    close=row.close,
                    return_pct=round(float((row.close / base - Decimal(1)) * 100), 4),
                )
            )
        else:
            out.append(DrillRevealHorizonOut(bars=h, date=None, close=None, return_pct=None))
    nxt = list(
        session.exec(
            select(PriceBar)
            .where(
                PriceBar.instrument_id == instrument_of(ctx.drill.ticker),
                PriceBar.interval == "1d",
                col(PriceBar.ts) > ctx.replay.end_at,
            )
            .order_by(col(PriceBar.ts))
            .limit(NEXT_BARS)
        ).all()
    )
    return out, nxt


__all__ = [
    "INLINE_SETUP_NAME",
    "METHOD",
    "DrillConflict",
    "DrillContext",
    "DrillError",
    "DrillNotFound",
    "after_trigger",
    "create_deck",
    "deck_drills",
    "deck_out",
    "delete_deck",
    "drill_session_ids",
    "is_hidden_session",
    "list_decks",
    "load_drill",
    "mask_for",
    "owned_deck",
    "plan_of",
    "plan_out",
    "put_plan",
    "require_plan",
    "reveal",
    "score_of",
    "status_of",
]
