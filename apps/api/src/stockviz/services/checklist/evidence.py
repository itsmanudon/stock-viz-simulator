"""The checklist's evidence grade (A2.4): what happened after a dimension
turned true, net of costs, against the base rate.

The study, for each dimension setup version (the ``checklist-evidence`` job,
weekly):

- **Event:** the first bar a dimension's rule is true after a bar it was
  false (``vector`` mode, which the conformance suite holds equal to point
  mode, so a value at a bar never depends on a later one). A bar after an
  unknown one is not an event: the state before it is not known.
- **Outcome:** the forward ``HORIZON`` (20) session return from that bar's
  close to the close 20 stored bars later (split-adjusted closes; dividends
  are not added), **net of the venue's fee schedule** for a round trip
  (``services/simulation/fees.py``: buy at the event close, sell at the exit
  close, ``NOTIONAL`` in the listing's currency): ``us_equity_2026`` for US
  listings, ``in_delivery_nse_2026`` / ``in_delivery_bse_2026`` for Indian.
- **Base rate:** the mean forward 20-session return, before costs, of every
  symbol in the same universe on the same date (US and Indian listings
  apart, by their index). Excess = an event's net return minus its date's
  base. So the grade asks: after the rule turned true, did a holder who paid
  the round trip beat simply holding the universe over the same 20 sessions?
- **Overlap:** an event within 20 bars of the last counted event on the same
  symbol is skipped (counted in ``overlapping_skipped``), so no two counted
  windows on one symbol share a day. Windows on different symbols on the
  same dates still correlate, which the t-statistic does not correct for.
- **Statistics:** n events, mean excess, its t-statistic (mean over its
  standard error, sample standard deviation), hit rate (share of events with
  excess above zero), mean net return and the mean base rate.
- **Grade** (design note question 5, fixed and published): ``A`` when t >= 3
  and mean excess >= 1%; ``B`` when t >= 2; ``C`` when t >= 1; ``D``
  otherwise; ``insufficient`` under ``MIN_EVENTS`` (30) events.

**No look-ahead past the window.** The data is cut at the window's end before
anything is computed: an event needs its exit bar on or before the end, and
nothing after the end is read (``tests/test_checklist_evidence.py`` perturbs
every bar after the window and finds the result unchanged).

The universe is the pinned symbol list with today's provider history
(``backtest/universe.py::evidence_universe``): survivorship-biased until
A1.4b's point-in-time universes, and every grade says so. This measures
association, not cause, and grades are not advice.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import numpy as np
import pandas as pd
from sqlmodel import Session, col, select

from stockviz import _time
from stockviz.models import ChecklistEvidence, Symbol
from stockviz.services.backtest.universe import evidence_universe
from stockviz.services.checklist.dimensions import Variant, in_scope, load_variants
from stockviz.services.dsl import CompiledRule, load_symbol, vector
from stockviz.services.dsl.data import Needs, SymbolData
from stockviz.services.instruments import is_index_ticker
from stockviz.services.markets.calendar import latest_completed_session
from stockviz.services.simulation.contracts import OrderSide
from stockviz.services.simulation.fees import (
    IN_DELIVERY_BSE_2026,
    IN_DELIVERY_NSE_2026,
    NONE,
    US_EQUITY_2026,
    FeeSchedule,
)

HORIZON = 20
MIN_EVENTS = 30
WINDOW_YEARS = 10
NOTIONAL = Decimal(100_000)
"""Each event buys this much (in the listing's currency) at the event close.
Fixed per-trade charges (FINRA's cap, the DP charge) make costs depend on
size; 100,000 is the size the grade assumes."""

GRADE_A_T = 3.0
GRADE_A_EFFECT = 0.01
GRADE_B_T = 2.0
GRADE_C_T = 1.0

SCHEDULE_BY_VENUE: dict[str, FeeSchedule] = {
    "XNYS": US_EQUITY_2026,
    "XNAS": US_EQUITY_2026,
    "XNSE": IN_DELIVERY_NSE_2026,
    "XBOM": IN_DELIVERY_BSE_2026,
}


def schedule_for(venue: str) -> FeeSchedule:
    return SCHEDULE_BY_VENUE.get(venue, NONE)


def round_trip_cost(
    schedule: FeeSchedule,
    entry: float,
    exit_: float,
    *,
    on_entry: date | None = None,
    on_exit: date | None = None,
) -> float:
    """Fees for buying ``NOTIONAL`` at ``entry`` and selling at ``exit_``, as a
    fraction of the amount bought. Without dates the schedule's newest
    version prices both legs (the checklist's grades); A4.5's scan event study
    passes each leg's date, so the version in force then applies."""
    price_in = Decimal(str(entry))
    price_out = Decimal(str(exit_))
    quantity = NOTIONAL / price_in
    fees = (
        schedule.fees(OrderSide.BUY, quantity, price_in, on=on_entry).total
        + schedule.fees(OrderSide.SELL, quantity, price_out, on=on_exit).total
    )
    return float(fees / (quantity * price_in))


def grade(n: int, mean_excess: float | None, t: float | None) -> str:
    if n < MIN_EVENTS or mean_excess is None:
        return "insufficient"
    tt = t if t is not None else 0.0
    if tt >= GRADE_A_T and mean_excess >= GRADE_A_EFFECT:
        return "A"
    if tt >= GRADE_B_T:
        return "B"
    if tt >= GRADE_C_T:
        return "C"
    return "D"


@dataclass(frozen=True)
class Event:
    ticker: str
    day: date
    gross: float
    cost: float
    base: float

    @property
    def net(self) -> float:
        return self.gross - self.cost

    @property
    def excess(self) -> float:
        return self.net - self.base


@dataclass
class StudyResult:
    start: date
    end: date
    horizon: int
    symbols: int = 0
    events: list[Event] = field(default_factory=list)
    overlapping_skipped: int = 0
    base_rate: float | None = None
    fee_schedules: dict[str, int] = field(default_factory=dict)
    incomplete: int = 0
    """A4.5 (shared events): events whose forward window ends after the window."""
    overlapping: int = 0
    """A4.5 (shared events): counted events whose window overlaps the previous
    counted one on the same symbol (they are kept; the t-statistic does not
    correct for it)."""

    @property
    def n(self) -> int:
        return len(self.events)

    @property
    def mean_net(self) -> float | None:
        return float(np.mean([e.net for e in self.events])) if self.events else None

    @property
    def mean_excess(self) -> float | None:
        return float(np.mean([e.excess for e in self.events])) if self.events else None

    @property
    def t_stat(self) -> float | None:
        if self.n < 2:
            return None
        values = np.array([e.excess for e in self.events])
        sd = float(values.std(ddof=1))
        if sd == 0 or not math.isfinite(sd):
            return None
        return float(values.mean() / (sd / math.sqrt(self.n)))

    @property
    def hit_rate(self) -> float | None:
        if not self.events:
            return None
        return float(np.mean([e.excess > 0 for e in self.events]))

    @property
    def grade(self) -> str:
        return grade(self.n, self.mean_excess, self.t_stat)


def _group(data: SymbolData) -> str:
    return data.benchmark_ticker or data.venue


def study(
    datasets: list[SymbolData],
    rule: CompiledRule,
    *,
    start: date,
    end: date,
    horizon: int = HORIZON,
) -> StudyResult:
    """The evidence study for one rule over ``datasets`` (pure): the
    checklist's and the indicator badges' grade."""
    return study_horizons(datasets, rule, start=start, end=end, horizons=(horizon,))[horizon]


def study_horizons(
    datasets: list[SymbolData],
    rule: CompiledRule,
    *,
    start: date,
    end: date,
    horizons: tuple[int, ...] = (HORIZON,),
    cooldown: int | None = None,
    dated_costs: bool = False,
) -> dict[int, StudyResult]:
    """One study per horizon, from one vector-mode evaluation per symbol.

    ``cooldown=None`` is the checklist's rule, per horizon: an event within
    ``horizon`` bars of the last counted event on its symbol is skipped
    (``overlapping_skipped``), among events with a full forward window.
    An integer (A4.5, the scan event study) finds the events once for every
    horizon: an event within ``cooldown`` bars of the previous event on its
    symbol is skipped (0: none), and per horizon an event without a full
    forward window is ``incomplete``. ``dated_costs`` prices each leg with
    the schedule's version in force on its date."""
    results = {h: StudyResult(start=start, end=end, horizon=h) for h in horizons}
    base_sum: dict[int, dict[tuple[str, np.datetime64], float]] = {h: {} for h in horizons}
    base_n: dict[int, dict[tuple[str, np.datetime64], int]] = {h: {} for h in horizons}
    pending: dict[int, list[tuple[str, str, date, float, float]]] = {h: [] for h in horizons}
    start_ts, end_ts = pd.Timestamp(start), pd.Timestamp(end)
    for full in datasets:
        data = full.cut(end) if len(full.bars) and full.bars.index[-1] > end_ts else full
        n = len(data.bars)
        closes = data.bars["close"].to_numpy(dtype=float)
        days = data.bars.index
        stamps = days.to_numpy(dtype="datetime64[D]")
        dates = data.dates
        group = _group(data)
        schedule = schedule_for(data.venue)
        live = [h for h in horizons if n > h]
        if not live:
            continue
        state = rule_state(rule, data)
        forwards: dict[int, np.ndarray] = {}
        for h in live:
            results[h].symbols += 1
            with np.errstate(divide="ignore", invalid="ignore"):
                forward = np.full(n, np.nan)
                forward[: n - h] = closes[h:] / closes[: n - h] - 1.0
            forwards[h] = forward
            in_window = (days >= start_ts) & (days <= end_ts) & np.isfinite(forward)
            for i in np.flatnonzero(in_window):
                key = (group, stamps[i])
                base_sum[h][key] = base_sum[h].get(key, 0.0) + float(forward[i])
                base_n[h][key] = base_n[h].get(key, 0) + 1

        picks: list[tuple[int, int]] = []
        if cooldown is None:
            for h in live:
                forward = forwards[h]
                in_window = (days >= start_ts) & (days <= end_ts) & np.isfinite(forward)
                last_used = -(10**9)
                for i in np.flatnonzero(in_window):
                    if not is_edge(state, int(i)):
                        continue
                    if i - last_used < h:
                        results[h].overlapping_skipped += 1
                        continue
                    last_used = i
                    picks.append((h, int(i)))
        else:
            picks = _shared_events(state, days, start_ts, end_ts, live, forwards, cooldown, results)
        for h, i in picks:
            on_in = dates[i] if dated_costs else None
            on_out = dates[i + h] if dated_costs else None
            cost = round_trip_cost(schedule, closes[i], closes[i + h], on_entry=on_in,
                                   on_exit=on_out)  # fmt: skip
            r = results[h]
            r.fee_schedules[schedule.name] = r.fee_schedules.get(schedule.name, 0) + 1
            pending[h].append((data.ticker, group, dates[i], float(forwards[h][i]), cost))
    for h in horizons:
        r = results[h]
        for ticker, group, day, gross, cost in pending[h]:
            key = (group, np.datetime64(day, "D"))
            base = base_sum[h][key] / base_n[h][key]
            r.events.append(Event(ticker, day, gross, cost, base))
        total_n = sum(base_n[h].values())
        r.base_rate = sum(base_sum[h].values()) / total_n if total_n else None
    return results


def is_edge(state: np.ndarray, i: int) -> bool:
    """The event definition (A2.4, A4.5, A4.7's drills): bar ``i`` is true and
    the bar before it is false. A bar after an unknown one (NaN) is not an
    edge: the state before it is not known."""
    return i > 0 and state[i] == 1.0 and state[i - 1] == 0.0


def edge_indices(state: np.ndarray, in_dates: np.ndarray) -> list[int]:
    """Every false-to-true edge among the bars where ``in_dates`` is true, in
    bar order. ``state`` is a rule's vector series as floats (1.0 true, 0.0
    false, NaN unknown). The scan event study and the drills (A4.7) both read
    their triggers here, so they agree by construction."""
    return [i for i in (int(k) for k in np.flatnonzero(in_dates)) if is_edge(state, i)]


def rule_state(rule: CompiledRule, data: SymbolData) -> np.ndarray:
    """``rule``'s vector series on ``data`` as floats (NaN = unknown)."""
    return vector(rule, data).astype("Float64").to_numpy(dtype=float, na_value=np.nan)


def _shared_events(
    state: np.ndarray,
    days: Any,
    start_ts: Any,
    end_ts: Any,
    live: list[int],
    forwards: dict[int, np.ndarray],
    cooldown: int,
    results: dict[int, StudyResult],
) -> list[tuple[int, int]]:
    """A4.5: the events found once for every horizon (edge, then cooldown)."""
    picks: list[tuple[int, int]] = []
    in_dates = (days >= start_ts) & (days <= end_ts)
    last_event = -(10**9)
    last_counted = dict.fromkeys(live, -(10**9))
    for i in edge_indices(state, in_dates):
        if cooldown and i - last_event < cooldown:
            for h in live:
                results[h].overlapping_skipped += 1
            continue
        last_event = i
        for h in live:
            if not np.isfinite(forwards[h][i]):
                results[h].incomplete += 1
                continue
            if i - last_counted[h] < h:
                results[h].overlapping += 1
            last_counted[h] = i
            picks.append((h, i))
    return picks


# --- the job ------------------------------------------------------------------


@dataclass
class EvidenceRun:
    start: date
    end: date
    rows: list[ChecklistEvidence] = field(default_factory=list)


def _union(variants: list[Variant]) -> Needs:
    rules = [v.rule for v in variants]
    return Needs(
        benchmark=any(r.needs.benchmark for r in rules),
        fundamentals=any(r.needs.fundamentals for r in rules),
        news=any(r.needs.news for r in rules),
        delivery=any(r.needs.delivery for r in rules),
    )


def _store(
    session: Session, variant: Variant, result: StudyResult, now: datetime
) -> ChecklistEvidence:
    stamp = evidence_universe()
    assert variant.version.id is not None
    row = session.exec(
        select(ChecklistEvidence).where(
            ChecklistEvidence.setup_version_id == variant.version.id,
            ChecklistEvidence.universe == stamp.name,
            ChecklistEvidence.window_start == result.start,
            ChecklistEvidence.window_end == result.end,
            ChecklistEvidence.horizon == result.horizon,
        )
    ).first()
    if row is None:
        row = ChecklistEvidence(
            setup_version_id=variant.version.id,
            dimension=variant.dimension.key,
            scope=variant.scope,
            universe=stamp.name,
            point_in_time=stamp.point_in_time,
            survivorship_biased=stamp.survivorship_biased,
            window_start=result.start,
            window_end=result.end,
            horizon=result.horizon,
            grade=result.grade,
        )
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


def run_evidence(
    session: Session,
    *,
    end: date | None = None,
    start: date | None = None,
    horizon: int = HORIZON,
    now: datetime | None = None,
) -> EvidenceRun:
    """Grade every checklist dimension setup on the stored history."""
    now = now or _time.utcnow()
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)  # naive means UTC, as everywhere in the API
    end = end or latest_completed_session(now)
    start = start or end - timedelta(days=365 * WINDOW_YEARS)
    variants = list(load_variants(session).values())
    needs = _union(variants)
    tickers = sorted(
        t
        for t in session.exec(select(Symbol.ticker).where(col(Symbol.is_active))).all()
        if not is_index_ticker(t)
    )
    datasets = {t: load_symbol(session, t, end=end, needs=needs) for t in tickers}
    run = EvidenceRun(start=start, end=end)
    stamp_now = now.astimezone(UTC).replace(tzinfo=None)
    for variant in variants:
        chosen = [d for t, d in datasets.items() if in_scope(t, variant.dimension, variant.scope)]
        result = study(chosen, variant.rule, start=start, end=end, horizon=horizon)
        run.rows.append(_store(session, variant, result, stamp_now))
    session.commit()
    return run


__all__ = [
    "HORIZON",
    "MIN_EVENTS",
    "NOTIONAL",
    "EvidenceRun",
    "StudyResult",
    "edge_indices",
    "grade",
    "is_edge",
    "round_trip_cost",
    "rule_state",
    "run_evidence",
    "schedule_for",
    "study",
    "study_horizons",
]
