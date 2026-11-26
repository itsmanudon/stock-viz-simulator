"""'Is my edge real?' (A5.6, M10.3 stats): honest statistics over the journal.

Every figure is computed on read from the closed journal entries
(``entries.py``), the same round trips and the same net P&L and R the entry
pages show. Nothing is stored.

**Groups.** Overall, by setup version (the plan's), by setup tag, by mistake
tag and by source (paper, imported, replay). Paper, imported and replay are
never pooled by default: without ``source`` the overall, setup and tag groups
read paper and imported entries (your trades), ``source=replay`` reads replay
only, ``source=all`` pools all three. The by-source groups always list each
source on its own (they ignore ``source``).

**Per group** (closed entries only; open entries are counted and left out):

- ``n`` closed entries, ``wins`` (net P&L > 0), ``losses`` (< 0),
  ``breakeven`` (= 0);
- win rate = wins / n; average win and average loss (mean net P&L of each);
  payoff = average win / |average loss|; profit factor = gross wins /
  |gross losses|;
- expectancy in money = mean net P&L (fees included, estimated for imports);
  expectancy in R = mean R over the entries that have one (a plan with a
  stop), ``n_r`` of them;
- plan adherence = share of entries whose plan was locked before entry and
  scored that followed it (the drill's checks), ``adherence_n`` scored;
- average holding = mean calendar days from entry to exit; total net P&L.

**Bootstrap interval.** A 90% percentile interval for the expectancy (money
and R): the group's values in closing order are resampled ``RESAMPLES``
(5,000) times with the stationary bootstrap of Politis and Romano
(``risk.engine.stationary_indices``, the sampler the Phase 8 Monte Carlo and
the A4.3 drawdown fan share), mean block ``MEAN_BLOCK`` (3 trades, so short
streaks stay together), and the 5th and 95th percentiles of the resampled
means are the interval. The generator is seeded with ``SEED`` (20261126),
returned in the response, so a rerun gives the same interval.

**Under 30 closed entries** (A2.4's ``MIN_EVENTS``): counts only (n, wins,
losses, breakeven) and a sentence why: no expectancy, no interval, no rate,
no grade. The same rule holds for R: under 30 entries with R, no R figures.

**Money across currencies** is never summed: a group holding entries in
two currencies shows its R figures and counts, and its money figures are
null with a note.

**Live vs backtest drift.** For each setup version in the groups, the
newest saved A4.1 strategy run of yours whose entry is that version
(``experiment_runs.kind = 'strategy'``) is compared with the live (journal)
figures: expectancy in R, win rate and average holding, and the differences.
The classification: ``no_backtest``; ``backtest_no_r`` (no trade had a price
stop); ``too_few_live_trades`` (under 30 live entries with R);
``too_few_backtest_trades`` (under 30 closed backtest trades);
``consistent`` when the backtest's expectancy in R lies inside the live 90%
interval, else ``outside_interval``. A backtest's figures are in-sample (the
range it was tuned and looked at) unless its holdout was unlocked (A4.3); the
response says which.

This is association over your recorded trades, not cause, and not advice.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Literal

import numpy as np
from sqlmodel import Session, col, select

from stockviz.models import ExperimentRun
from stockviz.models.trade_plan import TradePlan
from stockviz.schemas import (
    EdgeBacktestOut,
    EdgeDriftOut,
    EdgeGroupOut,
    EdgeIntervalOut,
    EdgeStatsOut,
    StrategyBacktestOut,
)
from stockviz.services.backtest import trials
from stockviz.services.checklist.evidence import MIN_EVENTS
from stockviz.services.journal import entries as journal
from stockviz.services.risk.engine import stationary_indices
from stockviz.services.trading.books import resolve_book

SEED = 20261126
RESAMPLES = 5_000
MEAN_BLOCK = 3
LEVEL = 0.90

SourceFilter = Literal["paper", "imported", "replay", "all"]
LIVE_SOURCES = ("paper", "imported")
SOURCE_LABELS = {"paper": "Paper", "imported": "Imported", "replay": "Replay"}

HONESTY = (
    "These are your recorded trades only: past results of this sample, not a forecast.",
    "Survivorship: not applicable. Every trade you closed is counted, winners and losers.",
    f"Small samples are noise: a group with fewer than {MIN_EVENTS} closed trades shows "
    "counts only.",
    "Association, not cause: a setup or tag that did well may have done well for other reasons.",
    "Not advice. Nothing here ranks you against anyone else.",
)
IMPORTED_FEES_NOTE = (
    "Imported trades' charges are estimated from the dated fee schedules, not taken from "
    "the broker, so their net P&L and R are estimates."
)
COUNTS_ONLY = (
    "Counts only: {n} closed {trades}, under the {min} needed. Below {min} the average is "
    "noise, so no expectancy, interval or rate is shown."
)
R_COUNTS_ONLY = (
    "R needs a plan with a stop: {n} of these trades have one, under the {min} needed, so "
    "no R figures are shown."
)
MIXED_CURRENCY = (
    "Trades in {currencies}: money is not summed across currencies. R and counts are shown."
)
BOOTSTRAP_METHOD = (
    "90% stationary bootstrap interval of the mean (Politis and Romano), "
    f"{RESAMPLES:,} resamples in closing order, mean block {MEAN_BLOCK} trades, "
    "5th to 95th percentile, fixed seed."
)
DRIFT_TEXT = {
    "consistent": "The backtest's expectancy lies inside your live 90% interval.",
    "outside_interval": "The backtest's expectancy lies outside your live 90% interval.",
    "too_few_live_trades": "Too few live trades with R: {need} more needed to compare.",
    "too_few_backtest_trades": (
        "The backtest has {n} closed trades, under the {min} needed to compare."
    ),
    "no_backtest": "No backtest for this setup.",
    "backtest_no_r": "The backtest's trades had no price stop, so it has no R to compare.",
}


# --- the facts of each closed entry ---------------------------------------------------


@dataclass(frozen=True)
class Outcome:
    """One closed journal entry, as the stats read it."""

    entry_id: int
    source: str
    currency: str
    net_pnl: float
    r: float | None
    holding_days: int
    followed_plan: bool | None
    """The drill's verdict on a plan locked before entry; None when not scored."""
    fees_estimated: bool
    closed_at: datetime
    entry_date: date
    setup_version_id: int | None = None
    setup_label: str | None = None
    setup_tags: tuple[str, ...] = ()
    mistake_tags: tuple[str, ...] = ()
    portfolio_id: int | None = None
    # A7.6 (behaviour diagnostics): the entry's size, first fill and costs.
    entry_notional: float = 0.0
    opened_at: datetime | None = None
    time_known: bool = True
    venue: str = "XNYS"
    fees: float = 0.0
    gross_pnl: float = 0.0


@dataclass
class Collected:
    outcomes: list[Outcome] = field(default_factory=list)
    open_entries: list[tuple[str, int | None]] = field(default_factory=list)
    """(source, book) of each open entry: counted, never in the figures."""


def collect_outcomes(session: Session, user_id: int) -> Collected:
    """Every closed entry of the user (every book and replay), figures on read."""
    trips = journal.sync(session, user_id)
    plans: dict[int, TradePlan] = journal._plans(
        session, [t.plan_id for t in trips if t.plan_id is not None]
    )
    labels = journal._setup_labels(session, plans.values())
    out = Collected()
    for t in trips:
        if not t.trip.closed:
            out.open_entries.append((t.source, t.portfolio_id))
            continue
        assert t.row is not None and t.row.id is not None and t.trip.closed_at is not None
        plan = plans.get(t.plan_id) if t.plan_id else None
        computed = journal._compute(session, t, plan)
        score, _note = journal._adherence(t, computed, plan)
        first = t.trip.fills[0]
        version = plan.setup_version_id if plan else None
        out.outcomes.append(
            Outcome(
                entry_id=t.row.id,
                source=t.source,
                currency=t.currency,
                net_pnl=float(computed.figures.net_pnl),
                r=computed.r,
                holding_days=(computed.end_day - first.venue_date).days,
                followed_plan=score.followed_plan if score is not None else None,
                fees_estimated=computed.figures.fees_estimated,
                closed_at=t.trip.closed_at,
                entry_date=first.venue_date,
                setup_version_id=version,
                setup_label=labels.get(version) if version else None,
                setup_tags=tuple(t.row.setup_tags or ()),
                mistake_tags=tuple(t.row.mistake_tags or ()),
                portfolio_id=t.portfolio_id,
                entry_notional=float(computed.figures.buy_notional),
                opened_at=first.at,
                time_known=first.time_known,
                venue=t.venue,
                fees=float(computed.figures.fees),
                gross_pnl=float(computed.figures.realized),
            )
        )
    out.outcomes.sort(key=lambda o: (o.closed_at, o.entry_id))
    return out


# --- pure statistics ----------------------------------------------------------------------


def bootstrap_interval(
    values: Sequence[float],
    *,
    seed: int = SEED,
    resamples: int = RESAMPLES,
    mean_block: int = MEAN_BLOCK,
    level: float = LEVEL,
) -> tuple[float, float]:
    """The percentile interval of the mean under the stationary bootstrap.

    ``values`` in closing order. Each resample draws ``len(values)`` trades
    with :func:`stationary_indices` (mean block ``mean_block``; 1 is the iid
    bootstrap); the interval is the ``(1 - level) / 2`` and ``(1 + level) / 2``
    quantiles of the resampled means. Same seed, same interval."""
    n = len(values)
    if n == 0:
        raise ValueError("no values to resample")
    series = np.asarray(values, dtype=float)
    rng = np.random.default_rng(seed)
    total = np.zeros(resamples)
    for idx in stationary_indices(
        n, paths=resamples, horizon_days=n, mean_block=mean_block, rng=rng
    ):
        total += series[idx]
    means = total / n
    tail = (1.0 - level) / 2.0
    low, high = np.quantile(means, [tail, 1.0 - tail])
    return float(low), float(high)


def _mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _round(value: float | None, places: int = 6) -> float | None:
    return None if value is None else round(value, places)


def _interval(values: Sequence[float], seed: int) -> EdgeIntervalOut:
    low, high = bootstrap_interval(values, seed=seed)
    return EdgeIntervalOut(low=round(low, 6), high=round(high, 6), level=LEVEL)


def group_stats(
    outcomes: Sequence[Outcome],
    *,
    key: str,
    label: str,
    kind: str,
    seed: int = SEED,
) -> EdgeGroupOut:
    """One group's figures, or its counts only under ``MIN_EVENTS``."""
    n = len(outcomes)
    wins = [o.net_pnl for o in outcomes if o.net_pnl > 0]
    losses = [o.net_pnl for o in outcomes if o.net_pnl < 0]
    currencies = sorted({o.currency for o in outcomes})
    rs = [o.r for o in outcomes if o.r is not None]
    base: dict[str, Any] = {
        "n_r": len(rs),
        "key": key,
        "label": label,
        "kind": kind,
        "n": n,
        "wins": len(wins),
        "losses": len(losses),
        "breakeven": n - len(wins) - len(losses),
        "includes_imported": any(o.source == "imported" for o in outcomes),
        "currencies": currencies,
    }
    if n < MIN_EVENTS:
        trades = "trade" if n == 1 else "trades"
        return EdgeGroupOut(
            **base,
            counts_only=True,
            counts_only_reason=COUNTS_ONLY.format(n=n, trades=trades, min=MIN_EVENTS),
        )

    one_currency = len(currencies) == 1
    money: dict[str, Any] = {}
    if one_currency:
        nets = [o.net_pnl for o in outcomes]
        avg_win = _mean(wins)
        avg_loss = _mean(losses)
        money = {
            "currency": currencies[0],
            "avg_win": _round(avg_win, 2),
            "avg_loss": _round(avg_loss, 2),
            "expectancy": _round(_mean(nets), 2),
            "expectancy_interval": _interval(nets, seed),
            "total_net_pnl": round(sum(nets), 2),
        }
    payoff = (sum(wins) / len(wins)) / abs(sum(losses) / len(losses)) if wins and losses else None
    factor = sum(wins) / abs(sum(losses)) if losses else None
    r_fields: dict[str, Any] = {}
    if len(rs) >= MIN_EVENTS:
        r_fields["expectancy_r"] = _round(_mean(rs))
        r_fields["expectancy_r_interval"] = _interval(rs, seed)
    else:
        r_fields["r_note"] = R_COUNTS_ONLY.format(n=len(rs), min=MIN_EVENTS)
    scored = [o.followed_plan for o in outcomes if o.followed_plan is not None]
    adherence = sum(1 for s in scored if s) / len(scored) if scored else None
    return EdgeGroupOut(
        **base,
        counts_only=False,
        win_rate=_round(len(wins) / n),
        payoff=_round(payoff),
        profit_factor=_round(factor),
        avg_holding_days=_round(_mean([float(o.holding_days) for o in outcomes]), 2),
        adherence_rate=_round(adherence),
        adherence_n=len(scored),
        money_note=None
        if one_currency
        else MIXED_CURRENCY.format(currencies=" and ".join(currencies)),
        **money,
        **r_fields,
    )


# --- filters, groups and drift --------------------------------------------------------------


@dataclass
class EdgeFilters:
    book_id: int | None = None
    source: SourceFilter | None = None
    setup_version_id: int | None = None
    tag: str | None = None
    date_from: date | None = None
    date_to: date | None = None


def _keep(o: Outcome, f: EdgeFilters, *, ignore_source: bool = False) -> bool:
    if f.book_id is not None and o.portfolio_id != f.book_id:
        return False
    if not ignore_source:
        if f.source is None and o.source not in LIVE_SOURCES:
            return False
        if f.source not in (None, "all") and o.source != f.source:
            return False
    if f.setup_version_id is not None and o.setup_version_id != f.setup_version_id:
        return False
    if f.tag:
        tag = f.tag.strip().lower()
        if tag not in {t.lower() for t in (*o.setup_tags, *o.mistake_tags)}:
            return False
    if f.date_from and o.entry_date < f.date_from:
        return False
    return not (f.date_to and o.entry_date > f.date_to)


def _tag_groups(outcomes: Sequence[Outcome], attr: str, kind: str, seed: int) -> list[EdgeGroupOut]:
    groups: dict[str, tuple[str, list[Outcome]]] = {}
    for o in outcomes:
        for tag in getattr(o, attr):
            low = tag.lower()
            groups.setdefault(low, (tag, []))[1].append(o)
    return sorted(
        (
            group_stats(rows, key=f"{kind}:{low}", label=shown, kind=kind, seed=seed)
            for low, (shown, rows) in groups.items()
        ),
        key=lambda g: (-g.n, g.label.lower()),
    )


def _setup_groups(outcomes: Sequence[Outcome], seed: int) -> list[EdgeGroupOut]:
    groups: dict[int | None, list[Outcome]] = {}
    for o in outcomes:
        groups.setdefault(o.setup_version_id, []).append(o)
    out = []
    for vid, rows in groups.items():
        label = rows[0].setup_label or (f"Setup version {vid}" if vid else "No setup")
        g = group_stats(rows, key=f"setup:{vid or 'none'}", label=label, kind="setup", seed=seed)
        g.setup_version_id = vid
        out.append(g)
    return sorted(out, key=lambda g: (g.setup_version_id is None, -g.n, g.label.lower()))


def _metric(result: dict[str, Any], key: str) -> float | None:
    for m in (result.get("report") or {}).get("metrics") or []:
        if m.get("key") == key:
            value = m.get("value")
            return float(value) if value is not None else None
    return None


def family_key(result: dict[str, Any]) -> str | None:
    """The A4.3 strategy family of a stored result (its holdout unlock key)."""
    try:
        return trials.strategy_family(StrategyBacktestOut.model_validate(result)).key
    except ValueError:  # a stored result older than today's shape
        return None


def _backtest(session: Session, user_id: int, version_id: int) -> EdgeBacktestOut | None:
    row = session.exec(
        select(ExperimentRun)
        .where(
            col(ExperimentRun.user_id) == user_id,
            col(ExperimentRun.kind) == "strategy",
            col(ExperimentRun.setup_version_id) == version_id,
        )
        .order_by(col(ExperimentRun.created_at).desc(), col(ExperimentRun.id).desc())
    ).first()
    if row is None or row.id is None:
        return None
    result = row.result or {}
    trades = [t for t in result.get("trades") or [] if not t.get("open")]
    rs = [float(t["r_multiple"]) for t in trades if t.get("r_multiple") is not None]
    wins = [t for t in trades if float(t.get("pnl") or 0) > 0]
    holding = [
        (date.fromisoformat(str(t["exit_date"])) - date.fromisoformat(str(t["entry_date"]))).days
        for t in trades
        if t.get("entry_date") and t.get("exit_date")
    ]
    window = result.get("window") or {}
    mode = window.get("holdout") or "none"
    key = family_key(result)
    unlock = trials.unlock_of(session, user_id, key) if key else None
    unlocked_at = unlock.unlocked_at if unlock is not None else None
    if unlocked_at is not None:
        sample, note = (
            "holdout_seen",
            "Its holdout was unlocked, so this rule has been seen out of sample too. The "
            "figures below are the run's own range.",
        )
    elif mode == "none":
        sample, note = (
            "in_sample",
            "In-sample: the run used its whole range with no holdout, the range you looked at.",
        )
    else:
        sample, note = (
            "in_sample",
            f"In-sample: the first 80% of the range (to {window.get('to_date')}). The holdout "
            f"({window.get('holdout_from')} to {window.get('holdout_to')}) is still locked.",
        )
    return EdgeBacktestOut(
        run_id=row.id,
        created_at=row.created_at,
        ticker=row.ticker,
        closed_trades=len(trades),
        n_r=len(rs),
        expectancy_r=_round(_mean(rs)),
        win_rate=_round(len(wins) / len(trades)) if trades else None,
        avg_holding_days=_round(_mean([float(h) for h in holding]), 2),
        report_expectancy_r=_metric(result, "expectancy_r"),
        holdout=mode,
        sample=sample,
        sample_note=note,
        unlocked_at=unlocked_at,
    )


def _diff(a: float | None, b: float | None) -> float | None:
    return None if a is None or b is None else round(a - b, 6)


def drift_for(live: EdgeGroupOut, backtest: EdgeBacktestOut | None) -> EdgeDriftOut:
    """Live (journal) against the newest saved backtest for one setup version."""
    status: str
    if backtest is None:
        status = "no_backtest"
    elif backtest.expectancy_r is None:
        status = "backtest_no_r"
    elif live.n_r < MIN_EVENTS or live.expectancy_r_interval is None:
        status = "too_few_live_trades"
    elif backtest.closed_trades < MIN_EVENTS:
        status = "too_few_backtest_trades"
    else:
        lo, hi = live.expectancy_r_interval.low, live.expectancy_r_interval.high
        status = "consistent" if lo <= backtest.expectancy_r <= hi else "outside_interval"
    text = DRIFT_TEXT[status].format(
        need=max(0, MIN_EVENTS - live.n_r),
        n=backtest.closed_trades if backtest else 0,
        min=MIN_EVENTS,
    )
    comparable = status in ("consistent", "outside_interval")
    return EdgeDriftOut(
        setup_version_id=live.setup_version_id or 0,
        label=live.label,
        status=status,  # pyright: ignore[reportArgumentType]
        text=text,
        live_n=live.n,
        live_n_r=live.n_r,
        live_expectancy_r=live.expectancy_r,
        live_interval=live.expectancy_r_interval,
        live_win_rate=live.win_rate,
        live_avg_holding_days=live.avg_holding_days,
        backtest=backtest,
        diff_expectancy_r=_diff(live.expectancy_r, backtest.expectancy_r if backtest else None)
        if comparable
        else None,
        diff_win_rate=_diff(live.win_rate, backtest.win_rate if backtest else None),
        diff_avg_holding_days=_diff(
            live.avg_holding_days, backtest.avg_holding_days if backtest else None
        ),
    )


def edge_stats(
    session: Session, user_id: int, filters: EdgeFilters, *, seed: int = SEED
) -> EdgeStatsOut:
    if filters.book_id is not None:
        resolve_book(session, user_id, filters.book_id)  # another user's book: 404
    collected = collect_outcomes(session, user_id)
    every = collected.outcomes
    kept = [o for o in every if _keep(o, filters)]
    by_source_rows = [o for o in every if _keep(o, filters, ignore_source=True)]
    overall_label = {
        None: "Your trades (paper and imported)",
        "all": "All trades (paper, imported and replay)",
    }.get(filters.source, f"{SOURCE_LABELS.get(filters.source or '', '')} trades")
    overall = group_stats(kept, key="overall", label=overall_label, kind="overall", seed=seed)
    by_setup = _setup_groups(kept, seed)
    by_source = [
        group_stats(
            [o for o in by_source_rows if o.source == s],
            key=f"source:{s}",
            label=SOURCE_LABELS[s],
            kind="source",
            seed=seed,
        )
        for s in ("paper", "imported", "replay")
        if any(o.source == s for o in by_source_rows)
    ]
    drift = [
        drift_for(g, _backtest(session, user_id, g.setup_version_id))
        for g in by_setup
        if g.setup_version_id is not None
    ]
    imported = any(o.source == "imported" for o in kept)
    notes = list(HONESTY)
    if imported:
        notes.append(IMPORTED_FEES_NOTE)
    return EdgeStatsOut(
        book_id=filters.book_id,
        source=filters.source,
        sources_included=sorted({o.source for o in kept})
        or (list(LIVE_SOURCES) if filters.source is None else []),
        setup_version_id=filters.setup_version_id,
        tag=filters.tag,
        date_from=filters.date_from,
        date_to=filters.date_to,
        min_closed=MIN_EVENTS,
        seed=seed,
        resamples=RESAMPLES,
        mean_block=MEAN_BLOCK,
        interval_level=LEVEL,
        method=BOOTSTRAP_METHOD,
        open_excluded=sum(
            1
            for source, book in collected.open_entries
            if (filters.book_id is None or book == filters.book_id)
            and (
                filters.source == "all"
                or source == filters.source
                or (filters.source is None and source in LIVE_SOURCES)
            )
        ),
        overall=overall,
        by_setup=by_setup,
        by_setup_tag=_tag_groups(kept, "setup_tags", "setup_tag", seed),
        by_mistake_tag=_tag_groups(kept, "mistake_tags", "mistake_tag", seed),
        by_source=by_source,
        drift=drift,
        imported_fees_estimated=imported,
        honesty=notes,
    )


__all__ = [
    "LEVEL",
    "MEAN_BLOCK",
    "RESAMPLES",
    "SEED",
    "EdgeFilters",
    "Outcome",
    "bootstrap_interval",
    "collect_outcomes",
    "drift_for",
    "edge_stats",
    "group_stats",
]
