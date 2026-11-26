"""A deck's triggers (A4.7, M9.3): the rule's real false-to-true dates.

- **Triggers** are the edges of the rule's vector series, found by
  ``checklist/evidence.py::edge_indices``, the code the scan event study
  (A4.5) counts its events with: a bar where the rule is true and the bar
  before it false (a bar after an unknown one is not a trigger), on every
  symbol of the universe, between ``from`` and ``to``. No cooldown.
- **Sessions.** Each trigger's replay session starts ``lead_bars`` (N)
  stored daily bars before the trigger and ends ``follow_bars`` (M) after
  it, both clamped to the stored bars. The drill opens at the trigger bar,
  with the lead-in visible.
- **The 30-day lag** (A4.6) applies to NSE/BSE symbols: a trigger whose
  session would end inside it is skipped and counted (``lag_skipped``),
  unless the owner's override lists the user.
- **Sampling.** The eligible triggers, sorted by (date, ticker), are sampled
  without replacement with ``random.Random(seed)``; the seed is stored, so a
  deck can be drawn again. With K at least the eligible count, the deck holds
  them all.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, datetime

import pandas as pd
from sqlmodel import Session, col, select

from stockviz.models import PriceBar
from stockviz.services.bars.resample import bar_date
from stockviz.services.checklist.evidence import edge_indices, rule_state
from stockviz.services.dsl import CompiledRule
from stockviz.services.dsl.data import SymbolData
from stockviz.services.instruments import instrument_of
from stockviz.services.markets.calendar import venue_for_ticker
from stockviz.services.replay.lag import end_inside_lag, lag_waived_for


@dataclass(frozen=True)
class Trigger:
    ticker: str
    day: date


@dataclass(frozen=True)
class Window:
    trigger: Trigger
    trigger_at: datetime
    start_at: datetime
    end_at: datetime


@dataclass
class Draw:
    found: list[Trigger]
    eligible: list[Window]
    lag_skipped: int
    no_bar: int
    chosen: list[Window]


def find_triggers(datasets: list[SymbolData], rule: CompiledRule, *, start: date, end: date):
    """Every false-to-true edge in ``[start, end]``, sorted by (date, ticker)."""
    out: list[Trigger] = []
    start_ts, end_ts = pd.Timestamp(start), pd.Timestamp(end)
    for full in datasets:
        data = full.cut(end) if len(full.bars) and full.bars.index[-1] > end_ts else full
        if len(data.bars) < 2:
            continue
        state = rule_state(rule, data)
        days = data.bars.index
        in_dates = (days >= start_ts) & (days <= end_ts)
        dates = data.dates
        out.extend(Trigger(data.ticker, dates[i]) for i in edge_indices(state, in_dates))
    out.sort(key=lambda t: (t.day, t.ticker))
    return out


def _bar_stamps(session: Session, ticker: str) -> list[datetime]:
    return list(
        session.exec(
            select(PriceBar.ts)
            .where(PriceBar.instrument_id == instrument_of(ticker), PriceBar.interval == "1d")
            .order_by(col(PriceBar.ts))
        ).all()
    )


def draw(
    session: Session,
    triggers: list[Trigger],
    *,
    k: int,
    lead_bars: int,
    follow_bars: int,
    seed: int,
    user_id: int,
    today: date | None = None,
) -> Draw:
    windows: list[Window] = []
    lag_skipped = 0
    no_bar = 0
    stamps: dict[str, list[datetime]] = {}
    index: dict[str, dict[date, int]] = {}
    waived = lag_waived_for(user_id)
    for t in triggers:
        if t.ticker not in stamps:
            rows = _bar_stamps(session, t.ticker)
            venue = venue_for_ticker(t.ticker)
            stamps[t.ticker] = rows
            index[t.ticker] = {bar_date(ts, venue): i for i, ts in enumerate(rows)}
        rows = stamps[t.ticker]
        i = index[t.ticker].get(t.day)
        if i is None:
            no_bar += 1
            continue
        start_i = max(0, i - lead_bars)
        end_i = min(len(rows) - 1, i + follow_bars)
        if end_i - start_i < 1:
            no_bar += 1
            continue
        if not waived and end_inside_lag(t.ticker, rows[end_i], today=today) is not None:
            lag_skipped += 1
            continue
        windows.append(Window(t, rows[i], rows[start_i], rows[end_i]))
    rng = random.Random(seed)
    chosen = rng.sample(windows, min(k, len(windows)))
    return Draw(triggers, windows, lag_skipped, no_bar, chosen)


def offset_weeks(seed: int, position: int, *, shown_end_limit: int | None = None) -> int:
    """A drill's date shift in whole weeks: 52 to 520, earlier or later. A
    later shift that would show dates past today (``shown_end_limit``: the
    most weeks later allowed) is turned into an earlier one."""
    rng = random.Random(f"drill-offset:{seed}:{position}")
    weeks = rng.randint(52, 520)
    if rng.random() < 0.5 and (shown_end_limit is None or weeks <= shown_end_limit):
        return -weeks
    return weeks


__all__ = ["Draw", "Trigger", "Window", "draw", "find_triggers", "offset_weeks"]
