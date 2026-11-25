"""Nightly checklist scores (A2.4): the ``checklist`` job.

For every active symbol (indices excluded), each of the six dimensions is
judged on the symbol's venue session: the newest stored daily bar of the
venue's active symbols on or before its latest completed session (the
screener's rule, ``screener_rule.venue_sessions``). A symbol without a bar
that day is ``unknown`` on every dimension ("no bar for D; latest D'"), never
judged on stale prices.

A dimension's result is its setup's rule (the ``and`` of its conditions) in
point mode at that bar, ``dsl.evaluate_at``, the code the conformance suite
holds equal to vector mode. Each condition is judged too, for the page's
detail; :func:`stockviz.services.checklist.dimensions.aggregate` of them
equals the dimension's result (Kleene, tested).

One row per (instrument, session date) in ``checklist_scores``: a rerun of
the night replaces it, so the job is idempotent.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from sqlmodel import Session, col, select

from stockviz import _time
from stockviz.models import ChecklistScore, Symbol
from stockviz.services.checklist.dimensions import (
    DIMENSIONS,
    Variant,
    aggregate,
    load_variants,
    scope_for,
)
from stockviz.services.dsl import CompiledRule, evaluate_at, load_symbol
from stockviz.services.dsl.data import Needs, SymbolData
from stockviz.services.instruments import instrument_ids, is_index_ticker
from stockviz.services.markets.calendar import latest_completed_session, venue_for_ticker
from stockviz.services.screener_rule import target_dates, venue_sessions

logger = logging.getLogger(__name__)


@dataclass
class ChecklistRun:
    session_date: date
    symbols: int = 0
    sessions: dict[str, date] = field(default_factory=dict)
    met_histogram: dict[int, int] = field(default_factory=dict)


def _needs(rules: list[CompiledRule]) -> tuple[int | None, Needs]:
    lookbacks = [r.lookback for r in rules]
    lookback = None if any(lb is None for lb in lookbacks) else max(lb or 0 for lb in lookbacks)
    return lookback, Needs(
        benchmark=any(r.needs.benchmark for r in rules),
        fundamentals=any(r.needs.fundamentals for r in rules),
        news=any(r.needs.news for r in rules),
        delivery=any(r.needs.delivery for r in rules),
    )


def _reason(status: str, reasons: tuple[str, ...]) -> str | None:
    if status != "unknown":
        return None
    return "; ".join(reasons) or "data the rule needs is missing"


def judge(variant: Variant, data: SymbolData, day: date) -> dict:
    """One dimension on one symbol's bar ``day``: its status, reason and conditions."""
    conditions = []
    for condition, rule in variant.conditions:
        outcome, _rows = evaluate_at(rule, data, day)
        conditions.append(
            {
                "label": condition.label,
                "rule": rule.canonical_text,
                "status": outcome.status,
                "reason": _reason(outcome.status, outcome.reasons),
            }
        )
    outcome, _rows = evaluate_at(variant.rule, data, day)
    status = outcome.status
    reason = _reason(status, outcome.reasons)
    if status == "not_met":
        failed = [c["label"] for c in conditions if c["status"] == "not_met"]
        reason = "not met: " + "; ".join(failed)
    return {
        "key": variant.dimension.key,
        "scope": variant.scope,
        "setup_version_id": variant.version.id,
        "status": status,
        "reason": reason,
        "conditions": conditions,
    }


def _unknown(variant: Variant, reason: str) -> dict:
    return {
        "key": variant.dimension.key,
        "scope": variant.scope,
        "setup_version_id": variant.version.id,
        "status": "unknown",
        "reason": reason,
        "conditions": [
            {"label": c.label, "rule": r.canonical_text, "status": "unknown", "reason": reason}
            for c, r in variant.conditions
        ],
    }


def score_symbol(
    session: Session, ticker: str, variants: dict[tuple[str, str], Variant], day: date | None
) -> list[dict]:
    """The six dimension results for ``ticker`` on its venue session ``day``."""
    chosen = [variants[(d.key, scope_for(ticker, d))] for d in DIMENSIONS]
    if day is None:
        return [_unknown(v, "no daily bars on this venue yet") for v in chosen]
    rules = [v.rule for v in chosen] + [r for v in chosen for _c, r in v.conditions]
    lookback, needs = _needs(rules)
    data = load_symbol(session, ticker, end=day, start=day, lookback=lookback, needs=needs)
    if data.bars.empty:
        return [_unknown(v, f"no daily bars on or before {day.isoformat()}") for v in chosen]
    last = data.dates[-1]
    if last != day:
        reason = f"no bar for {day.isoformat()}; latest {last.isoformat()}"
        return [_unknown(v, reason) for v in chosen]
    return [judge(v, data, day) for v in chosen]


def counts(dimensions: list[dict]) -> tuple[int, int]:
    met = sum(1 for d in dimensions if d["status"] == "met")
    evaluated = sum(1 for d in dimensions if d["status"] in ("met", "not_met"))
    return met, evaluated


def run_checklist(session: Session, *, now: datetime | None = None) -> ChecklistRun:
    """Score every active symbol and upsert ``checklist_scores``."""
    now = now or _time.utcnow()
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)  # naive means UTC, as everywhere in the API
    variants = load_variants(session)
    tickers = sorted(
        t
        for t in session.exec(select(Symbol.ticker).where(col(Symbol.is_active))).all()
        if not is_index_ticker(t)
    )
    venues = {venue_for_ticker(t) for t in tickers}
    sessions = venue_sessions(session, target_dates(venues, as_of=None, now=now))
    ids = instrument_ids(session, tickers)
    run = ChecklistRun(session_date=latest_completed_session(now), sessions=sessions)
    for ticker in tickers:
        instrument_id = ids.get(ticker)
        if instrument_id is None:
            logger.warning("checklist: %s has no instrument; skipped", ticker)
            continue
        day = sessions.get(venue_for_ticker(ticker))
        dimensions = score_symbol(session, ticker, variants, day)
        session_date = day or run.session_date
        met, evaluated = counts(dimensions)
        row = session.exec(
            select(ChecklistScore).where(
                ChecklistScore.instrument_id == instrument_id,
                ChecklistScore.session_date == session_date,
            )
        ).first()
        if row is None:
            row = ChecklistScore(instrument_id=instrument_id, session_date=session_date)
        row.dimensions = dimensions
        row.met_count = met
        row.evaluated_count = evaluated
        row.computed_at = now.astimezone(UTC).replace(tzinfo=None)
        session.add(row)
        session.commit()
        run.symbols += 1
        run.met_histogram[met] = run.met_histogram.get(met, 0) + 1
    return run


__all__ = ["ChecklistRun", "aggregate", "counts", "judge", "run_checklist", "score_symbol"]
