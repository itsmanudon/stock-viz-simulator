"""Behaviour diagnostics (A7.6, M10.4), on read from closed journal entries.

Every figure comes from A5.6's outcomes (``edge.collect_outcomes``, the same
net P&L, plans and fees as the entry pages); nothing is stored. Wording is
neutral: these describe what the record shows, never what to do.

- **Execution discipline:** the share of entries with a plan locked before
  entry that followed it (the drill's score), apart from how they turned out.
- **Disposition index:** mean holding (calendar days) of losing entries over
  that of winning ones. Above 1: losers were held longer than winners.
- **Tiltmeter:** an entry opened after a losing close (the latest entry closed
  before it opened lost money) whose size is more than ``TILT_RATIO`` x the
  median size of the ``TILT_WINDOW`` entries before it. Size is the opening
  notional (in the entry's currency; books in one currency compare cleanly).
- **Heatmaps:** entries, net P&L and win rate by weekday and by hour of the
  first fill, in the venue's time zone (entries with an unknown time are left
  out of the hour map).
- **Cost leakage:** fees paid (estimated for imported books) in total, per
  entry and as a share of gross P&L (realised before fees).

Under ``MIN_ENTRIES`` closed entries the rates are null with the reason; the
counts still show.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from statistics import median
from zoneinfo import ZoneInfo

from stockviz.services.journal.edge import Outcome
from stockviz.services.markets.calendar import venue_zone

MIN_ENTRIES = 30
TILT_RATIO = 1.5
TILT_WINDOW = 20
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


@dataclass
class Cell:
    key: str
    entries: int = 0
    wins: int = 0
    net_pnl: float = 0.0

    def out(self) -> dict[str, object]:
        return {
            "key": self.key,
            "entries": self.entries,
            "net_pnl": round(self.net_pnl, 6),
            "win_rate": round(self.wins / self.entries, 4) if self.entries else None,
        }


@dataclass
class Behaviour:
    entries: int
    counts_only: bool
    reason: str | None
    discipline_scored: int = 0
    discipline_followed: int = 0
    discipline_rate: float | None = None
    winners: int = 0
    losers: int = 0
    avg_hold_winners: float | None = None
    avg_hold_losers: float | None = None
    disposition_index: float | None = None
    tilt_entries: list[int] = field(default_factory=list)
    tilt_rate: float | None = None
    by_weekday: list[dict[str, object]] = field(default_factory=list)
    by_hour: list[dict[str, object]] = field(default_factory=list)
    fees_total: float = 0.0
    fees_per_entry: float | None = None
    fees_share_of_gross: float | None = None
    fees_estimated: bool = False
    currencies: list[str] = field(default_factory=list)


def _mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def tilt_flags(outcomes: Sequence[Outcome]) -> list[int]:
    """Entry ids opened after a losing close at more than 1.5x the recent median size."""
    by_open = sorted(
        (o for o in outcomes if o.opened_at is not None),
        key=lambda o: (o.opened_at, o.entry_id),  # type: ignore[arg-type, return-value]
    )
    flagged: list[int] = []
    for i, o in enumerate(by_open):
        before = by_open[max(0, i - TILT_WINDOW) : i]
        sizes = [b.entry_notional for b in before if b.entry_notional > 0]
        if len(sizes) < 5:
            continue
        closed_before = [b for b in outcomes if b.closed_at < o.opened_at]  # type: ignore[operator]
        if not closed_before:
            continue
        last = max(closed_before, key=lambda b: (b.closed_at, b.entry_id))
        if last.net_pnl < 0 and o.entry_notional > TILT_RATIO * median(sizes):
            flagged.append(o.entry_id)
    return flagged


def behaviour(outcomes: Sequence[Outcome]) -> Behaviour:
    n = len(outcomes)
    short = n < MIN_ENTRIES
    out = Behaviour(
        entries=n,
        counts_only=short,
        reason=(f"{n} closed entries; the rates need {MIN_ENTRIES}." if short else None),
    )
    out.currencies = sorted({o.currency for o in outcomes})
    scored = [o for o in outcomes if o.followed_plan is not None]
    out.discipline_scored = len(scored)
    out.discipline_followed = sum(1 for o in scored if o.followed_plan)
    winners = [o for o in outcomes if o.net_pnl > 0]
    losers = [o for o in outcomes if o.net_pnl < 0]
    out.winners, out.losers = len(winners), len(losers)
    out.tilt_entries = tilt_flags(outcomes)
    if not short:
        if scored:
            out.discipline_rate = round(out.discipline_followed / len(scored), 4)
        hw = _mean([o.holding_days for o in winners])
        hl = _mean([o.holding_days for o in losers])
        out.avg_hold_winners = None if hw is None else round(hw, 2)
        out.avg_hold_losers = None if hl is None else round(hl, 2)
        if hw and hl is not None:
            out.disposition_index = round(hl / hw, 3)
        out.tilt_rate = round(len(out.tilt_entries) / n, 4)

    days = {d: Cell(d) for d in WEEKDAYS[:5]}
    hours: dict[int, Cell] = {}
    for o in outcomes:
        if o.opened_at is None:
            continue
        zone: ZoneInfo = venue_zone(o.venue)
        local = o.opened_at.replace(tzinfo=ZoneInfo("UTC")).astimezone(zone)
        day = WEEKDAYS[local.weekday()]
        cell = days.setdefault(day, Cell(day))
        cell.entries += 1
        cell.wins += o.net_pnl > 0
        cell.net_pnl += o.net_pnl
        if o.time_known:
            h = hours.setdefault(local.hour, Cell(f"{local.hour:02d}:00"))
            h.entries += 1
            h.wins += o.net_pnl > 0
            h.net_pnl += o.net_pnl
    out.by_weekday = [c.out() for c in days.values()]
    out.by_hour = [hours[h].out() for h in sorted(hours)]

    out.fees_total = round(sum(o.fees for o in outcomes), 6)
    out.fees_estimated = any(o.fees_estimated for o in outcomes)
    if n:
        out.fees_per_entry = round(out.fees_total / n, 6)
    gross = sum(abs(o.gross_pnl) for o in outcomes)
    if gross:
        out.fees_share_of_gross = round(out.fees_total / gross, 4)
    return out
