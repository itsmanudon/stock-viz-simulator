"""Indicator evidence badges (A3.4, M2.6): each study's canonical signal
graded by the A2.4 evidence study.

``run_indicator_evidence`` (``stockviz.cli indicator-evidence``) compiles
every rule in ``signals.SIGNALS``, loads every active non-index symbol once
with the union of what the rules read, and runs
``services/checklist/evidence.py::study`` per rule over the last 10 years to
the latest New York session: same event definition, horizon, fees, base rate,
overlap rule, grade thresholds and survivorship stamp as the checklist's
grades. Rows upsert on (rule hash, universe, window, horizon).

``latest_by_indicator`` reads, per study, the newest row whose ``rule_hash``
is the current rule's hash on the current universe, so a changed rule never
shows an old grade. A study with no signal, or no row yet, has no grade.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from sqlmodel import Session, col, select

from stockviz import _time
from stockviz.models import IndicatorEvidence, Symbol
from stockviz.services.backtest.universe import evidence_universe
from stockviz.services.checklist.evidence import HORIZON, WINDOW_YEARS, StudyResult, study
from stockviz.services.dsl import CompiledRule, compile_rule, load_symbol
from stockviz.services.dsl.data import Needs
from stockviz.services.indicators.signals import SIGNALS
from stockviz.services.instruments import is_index_ticker
from stockviz.services.markets.calendar import latest_completed_session


def compiled_signals(only: list[str] | None = None) -> dict[str, CompiledRule]:
    keys = [k for k in SIGNALS if only is None or k in only]
    return {k: compile_rule(SIGNALS[k].rule) for k in keys}


@dataclass
class IndicatorEvidenceRun:
    start: date
    end: date
    rows: list[IndicatorEvidence] = field(default_factory=list)


def _union(rules: list[CompiledRule]) -> Needs:
    return Needs(
        benchmark=any(r.needs.benchmark for r in rules),
        fundamentals=any(r.needs.fundamentals for r in rules),
        news=any(r.needs.news for r in rules),
        delivery=any(r.needs.delivery for r in rules),
    )


def _store(
    session: Session, key: str, rule: CompiledRule, result: StudyResult, now: datetime
) -> IndicatorEvidence:
    stamp = evidence_universe()
    row = session.exec(
        select(IndicatorEvidence).where(
            IndicatorEvidence.rule_hash == rule.hash,
            IndicatorEvidence.universe == stamp.name,
            IndicatorEvidence.window_start == result.start,
            IndicatorEvidence.window_end == result.end,
            IndicatorEvidence.horizon == result.horizon,
        )
    ).first()
    if row is None:
        row = IndicatorEvidence(
            indicator=key,
            rule=rule.canonical_text,
            rule_hash=rule.hash,
            universe=stamp.name,
            point_in_time=stamp.point_in_time,
            survivorship_biased=stamp.survivorship_biased,
            window_start=result.start,
            window_end=result.end,
            horizon=result.horizon,
            grade=result.grade,
        )
    row.indicator = key
    row.rule = rule.canonical_text
    row.point_in_time = stamp.point_in_time
    row.survivorship_biased = stamp.survivorship_biased
    row.symbols = result.symbols
    row.n_events = result.n
    row.overlapping_skipped = result.overlapping_skipped
    row.mean_net_return = result.mean_net
    row.base_rate = result.base_rate
    row.mean_excess = result.mean_excess
    row.t_stat = result.t_stat
    row.hit_rate = result.hit_rate
    row.grade = result.grade
    row.fee_schedules = dict(result.fee_schedules)
    row.computed_at = now
    session.add(row)
    return row


def run_indicator_evidence(
    session: Session,
    *,
    end: date | None = None,
    start: date | None = None,
    horizon: int = HORIZON,
    only: list[str] | None = None,
    now: datetime | None = None,
) -> IndicatorEvidenceRun:
    """Grade every study's canonical signal on the stored history."""
    now = now or _time.utcnow()
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    end = end or latest_completed_session(now)
    start = start or end - timedelta(days=365 * WINDOW_YEARS)
    rules = compiled_signals(only)
    needs = _union(list(rules.values()))
    tickers = sorted(
        t
        for t in session.exec(select(Symbol.ticker).where(col(Symbol.is_active))).all()
        if not is_index_ticker(t)
    )
    datasets = [load_symbol(session, t, end=end, needs=needs) for t in tickers]
    run = IndicatorEvidenceRun(start=start, end=end)
    stamp_now = now.astimezone(UTC).replace(tzinfo=None)
    for key, rule in rules.items():
        result = study(datasets, rule, start=start, end=end, horizon=horizon)
        run.rows.append(_store(session, key, rule, result, stamp_now))
    session.commit()
    return run


def latest_by_indicator(session: Session) -> dict[str, IndicatorEvidence]:
    """The newest graded row per study for its current rule and universe."""
    hashes = {k: r.hash for k, r in compiled_signals().items()}
    if not hashes:
        return {}
    stamp = evidence_universe()
    rows = session.exec(
        select(IndicatorEvidence)
        .where(
            col(IndicatorEvidence.rule_hash).in_(list(hashes.values())),
            IndicatorEvidence.universe == stamp.name,
        )
        .order_by(col(IndicatorEvidence.window_end).desc(), col(IndicatorEvidence.id).desc())
    ).all()
    out: dict[str, IndicatorEvidence] = {}
    for row in rows:
        for key, digest in hashes.items():
            if digest == row.rule_hash and key not in out:
                out[key] = row
    return out


__all__ = [
    "IndicatorEvidenceRun",
    "compiled_signals",
    "latest_by_indicator",
    "run_indicator_evidence",
]
