"""A6.10 (M9.5): "Replay my trade", a read-only playback of a journal entry.

For a paper or imported entry: the bars from a few sessions before the entry
to a few after the exit (stored 1-minute bars when they cover every session
of a closed entry with timed fills, else daily bars), the user's real fills,
the plan's levels, the entry's excursions (exact from minutes, else the A5
daily rule) and a hesitation strip: how long after the plan's entry level was
first touched the fill came, and whether a stop the price went through was
honoured. No orders: the web plays it back with the replay autoplay controls.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from decimal import Decimal

from sqlmodel import Session, col, select

from stockviz.models import IntradayBar, PriceBar, TradePlan
from stockviz.services.journal import entries as svc
from stockviz.services.markets.calendar import previous_session

CONTEXT_SESSIONS = 5
"""Daily bars shown before the entry and after the exit."""
MAX_MINUTES = 5_000
"""More stored minutes than this (a long trade) plays on daily bars instead."""


class TradeReplayNotOffered(ValueError):
    """The entry cannot be played back here (a replay session's own entry)."""


@dataclass(frozen=True)
class ReplayBar:
    ts: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int


@dataclass(frozen=True)
class Hesitation:
    entry_touched_at: datetime | None
    fill_at: datetime
    wait_bars: int | None
    stop_breached_at: datetime | None
    stop_honoured: bool | None
    exit_at: datetime | None
    exit_price: Decimal | None
    note: str


@dataclass(frozen=True)
class TradeReplay:
    trip: svc.Trip
    interval: str
    bars: list[ReplayBar]
    plan: TradePlan | None
    computed: object
    hesitation: Hesitation | None


def _minute_bars(session: Session, t: svc.Trip) -> list[ReplayBar] | None:
    """The entry's sessions, whole, from the feed the excursions used."""
    from stockviz.services.bars.intraday import FEED_RANK

    minutes = svc._minutes(session, t)
    if not minutes or not svc._minute_coverage(t, minutes):
        return None
    first = t.trip.fills[0].at.replace(second=0, microsecond=0) - timedelta(hours=1)
    last = max(f.at for f in t.trip.fills) + timedelta(hours=1)
    for feed in FEED_RANK:
        if feed == "replayed":
            continue
        rows = session.exec(
            select(IntradayBar)
            .where(
                col(IntradayBar.instrument_id) == t.instrument_id,
                col(IntradayBar.interval) == "1m",
                col(IntradayBar.feed) == feed,
                col(IntradayBar.ts) >= first,
                col(IntradayBar.ts) <= last,
            )
            .order_by(col(IntradayBar.ts))
            .limit(MAX_MINUTES + 1)
        ).all()
        if rows:
            if len(rows) > MAX_MINUTES:
                return None
            return [ReplayBar(r.ts, r.open, r.high, r.low, r.close, int(r.volume)) for r in rows]
    return None


def _daily_bars(session: Session, t: svc.Trip) -> list[ReplayBar]:
    start = t.trip.fills[0].venue_date
    for _ in range(CONTEXT_SESSIONS):
        start = previous_session(start, t.venue)
    stmt = select(PriceBar).where(
        col(PriceBar.instrument_id) == t.instrument_id,
        col(PriceBar.interval) == "1d",
        col(PriceBar.ts) >= datetime.combine(start, time.min),
    )
    rows = session.exec(stmt.order_by(col(PriceBar.ts))).all()
    if t.trip.closed:
        last = t.trip.fills[-1].venue_date
        after = [r for r in rows if r.ts.date() > last][:CONTEXT_SESSIONS]
        rows = [r for r in rows if r.ts.date() <= last] + after
    return [ReplayBar(r.ts, r.open, r.high, r.low, r.close, int(r.volume or 0)) for r in rows]


def _bar_index(bars: list[ReplayBar], at: datetime, interval: str) -> int | None:
    """The bar holding ``at`` (minutes: its minute; daily: its date)."""
    for i, bar in enumerate(bars):
        if interval == "1m":
            if bar.ts <= at < bar.ts + timedelta(minutes=1):
                return i
        elif bar.ts.date() == at.date():
            return i
    return None


def hesitation(
    t: svc.Trip, bars: list[ReplayBar], plan: TradePlan | None, interval: str
) -> Hesitation | None:
    if plan is None or not bars:
        return None
    short = t.trip.side == "short"
    opening = t.trip.opening_side
    entry_fill = next(f for f in t.trip.fills if f.side == opening)
    fill_index = _bar_index(bars, entry_fill.at, interval)
    note = "Minute bars." if interval == "1m" else "Daily bars, approximate."
    touched_at = None
    wait = None
    level = plan.planned_entry
    if fill_index is not None and level is not None:
        for i in range(fill_index + 1):
            if bars[i].low <= level <= bars[i].high:
                touched_at, wait = bars[i].ts, fill_index - i
                break
    exits = [f for f in t.trip.fills if f.side != opening]
    exit_fill = exits[-1] if t.trip.closed and exits else None
    breached_at = None
    honoured = None
    stop = plan.planned_stop
    if stop is not None and fill_index is not None:
        end = _bar_index(bars, exit_fill.at, interval) if exit_fill else len(bars) - 1
        end = len(bars) - 1 if end is None else end
        for bar in bars[fill_index + 1 : end + 1]:
            through = bar.high >= stop if short else bar.low <= stop
            if through:
                breached_at = bar.ts
                break
        if breached_at is not None:
            # Honoured when the position was closed on the bar the stop broke.
            exit_index = _bar_index(bars, exit_fill.at, interval) if exit_fill else None
            breach_index = next(i for i, b in enumerate(bars) if b.ts == breached_at)
            honoured = exit_index is not None and exit_index <= breach_index
    return Hesitation(
        entry_touched_at=touched_at,
        fill_at=entry_fill.at,
        wait_bars=wait,
        stop_breached_at=breached_at,
        stop_honoured=honoured,
        exit_at=exit_fill.at if exit_fill else None,
        exit_price=exit_fill.price if exit_fill else None,
        note=note,
    )


def trade_replay(session: Session, user_id: int, entry_id: int) -> TradeReplay:
    t = svc._find(session, user_id, entry_id)
    if t.source == "replay":
        raise TradeReplayNotOffered(
            "A replay session's entry plays back in the Replay Lab, not here"
        )
    plans = svc._plans(session, [t.plan_id] if t.plan_id else [])
    plan = plans.get(t.plan_id) if t.plan_id else None
    computed = svc._compute(session, t, plan)
    minutes = None
    if t.trip.closed and all(f.time_known for f in t.trip.fills):
        minutes = _minute_bars(session, t)
    interval = "1m" if minutes else "1d"
    bars = minutes if minutes else _daily_bars(session, t)
    return TradeReplay(
        trip=t,
        interval=interval,
        bars=bars,
        plan=plan,
        computed=computed,
        hesitation=hesitation(t, bars, plan, interval),
    )
