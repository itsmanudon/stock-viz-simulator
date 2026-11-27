"""The weekly journal review (A9.12, M11.6): one week's closed entries against
the weeks before, and a short list of things to look at. Deterministic and
pure over A5.6's outcomes: no model, nothing stored.

The week is the seven days ending ``week_end`` (inclusive), by each entry's
close date (UTC). The baseline is the ``BASELINE_WEEKS`` weeks before it.
"Look at" items come from fixed rules, in this order, each with the entries
it names: entries opened larger than usual after a losing close (A7.6's tilt
rule), scored plans not followed, entries with no plan locked before entry,
a mistake tag used at least twice, mean R well below the baseline, and more
entries than twice the baseline's weekly average. Wording is neutral; a
small week says so. It describes what was recorded, not skill.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta

from stockviz.services.journal.behaviour import tilt_flags
from stockviz.services.journal.edge import Outcome

BASELINE_WEEKS = 4
R_GAP = 0.5
SMALL_WEEK = 5


@dataclass
class WeekFigures:
    entries: int
    wins: int
    losses: int
    net_by_currency: dict[str, float]
    mean_r: float | None
    n_r: int
    plans_scored: int
    plans_followed: int
    no_plan: int


@dataclass(frozen=True)
class LookAt:
    key: str
    text: str
    entry_ids: tuple[int, ...] = ()


@dataclass
class WeeklyReview:
    week_start: date
    week_end: date
    week: WeekFigures
    baseline_weeks: int
    baseline_entries_per_week: float | None
    baseline_mean_r: float | None
    baseline_adherence: float | None
    look_at: list[LookAt] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def figures(outcomes: Sequence[Outcome]) -> WeekFigures:
    rs = [o.r for o in outcomes if o.r is not None]
    net: dict[str, float] = {}
    for o in outcomes:
        net[o.currency] = round(net.get(o.currency, 0.0) + o.net_pnl, 2)
    scored = [o for o in outcomes if o.followed_plan is not None]
    return WeekFigures(
        entries=len(outcomes),
        wins=sum(1 for o in outcomes if o.net_pnl > 0),
        losses=sum(1 for o in outcomes if o.net_pnl < 0),
        net_by_currency=net,
        mean_r=round(sum(rs) / len(rs), 3) if rs else None,
        n_r=len(rs),
        plans_scored=len(scored),
        plans_followed=sum(1 for o in scored if o.followed_plan),
        no_plan=sum(1 for o in outcomes if o.followed_plan is None and o.source != "replay"),
    )


def _ids(outcomes: Sequence[Outcome]) -> tuple[int, ...]:
    return tuple(o.entry_id for o in outcomes)


def review(all_outcomes: Sequence[Outcome], week_end: date) -> WeeklyReview:
    start = week_end - timedelta(days=6)
    base_start = start - timedelta(days=7 * BASELINE_WEEKS)
    week = [o for o in all_outcomes if start <= o.closed_at.date() <= week_end]
    base = [o for o in all_outcomes if base_start <= o.closed_at.date() < start]
    wf, bf = figures(week), figures(base)
    out = WeeklyReview(
        week_start=start,
        week_end=week_end,
        week=wf,
        baseline_weeks=BASELINE_WEEKS,
        baseline_entries_per_week=round(bf.entries / BASELINE_WEEKS, 2) if base else None,
        baseline_mean_r=bf.mean_r,
        baseline_adherence=(
            round(bf.plans_followed / bf.plans_scored, 3) if bf.plans_scored else None
        ),
    )
    if not week:
        out.notes.append("No entry closed this week.")
        return out
    if wf.entries < SMALL_WEEK:
        out.notes.append(
            f"{wf.entries} entr{'y' if wf.entries == 1 else 'ies'} this week: read the figures "
            "as a record, not a pattern."
        )
    if len({o.currency for o in week}) > 1:
        out.notes.append("Net P&L is shown per currency; currencies are not added together.")

    week_ids = {o.entry_id for o in week}
    tilted = [o for o in week if o.entry_id in set(tilt_flags(all_outcomes)) & week_ids]
    if tilted:
        out.look_at.append(LookAt(
            "tilt",
            f"{len(tilted)} entr{'y was' if len(tilted) == 1 else 'ies were'} opened at more than "
            "1.5x your recent median size right after a losing close.",
            _ids(tilted),
        ))  # fmt: skip
    missed = [o for o in week if o.followed_plan is False]
    if missed:
        out.look_at.append(LookAt(
            "plan_not_followed",
            f"{len(missed)} of {wf.plans_scored} scored plans were not followed (entry, stop or "
            "size outside the plan).",
            _ids(missed),
        ))  # fmt: skip
    unplanned = [o for o in week if o.followed_plan is None and o.source != "replay"]
    if unplanned:
        out.look_at.append(LookAt(
            "no_plan",
            f"{len(unplanned)} entr{'y' if len(unplanned) == 1 else 'ies'} had no plan locked "
            "before entry, so adherence could not be scored.",
            _ids(unplanned),
        ))  # fmt: skip
    tags = Counter(t.lower() for o in week for t in o.mistake_tags)
    for tag, n in tags.most_common(1):
        if n >= 2:
            named = [o for o in week if tag in (t.lower() for t in o.mistake_tags)]
            out.look_at.append(LookAt(
                "mistake_tag", f'You tagged "{tag}" {n} times this week.', _ids(named)
            ))  # fmt: skip
    if (
        wf.mean_r is not None and bf.mean_r is not None and wf.n_r >= 3 and bf.n_r >= 3
        and wf.mean_r < bf.mean_r - R_GAP
    ):  # fmt: skip
        out.look_at.append(LookAt(
            "r_below_baseline",
            f"Mean R was {wf.mean_r:+.2f} against {bf.mean_r:+.2f} over the previous "
            f"{BASELINE_WEEKS} weeks.",
        ))  # fmt: skip
    per_week = out.baseline_entries_per_week
    if per_week and per_week >= 1 and wf.entries > 2 * per_week:
        out.look_at.append(LookAt(
            "more_entries",
            f"{wf.entries} entries closed, against {per_week:g} a week over the previous "
            f"{BASELINE_WEEKS} weeks.",
        ))  # fmt: skip
    return out
