"""A2.4: the checklist evidence study (forward returns net of fees vs the base rate)."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, time
from decimal import Decimal
from itertools import pairwise

import numpy as np
import pandas as pd
import pytest
from sqlmodel import Session, select

from stockviz.models import ChecklistEvidence, PriceBar
from stockviz.services.checklist.evidence import (
    MIN_EVENTS,
    NOTIONAL,
    grade,
    round_trip_cost,
    run_evidence,
    study,
)
from stockviz.services.dsl import compile_rule
from stockviz.services.dsl.data import SymbolData, bars_frame
from stockviz.services.simulation.contracts import OrderSide
from stockviz.services.simulation.fees import IN_DELIVERY_NSE_2026, US_EQUITY_2026
from tests.symbols import seed_symbols

DAYS: list[date] = [d.date() for d in pd.bdate_range("2018-01-01", periods=1200)]
START, END = DAYS[100], DAYS[1100]
SPIKE = compile_rule("volume > 3000")


def _symbol(i: int, *, planted: bool, seed: int, venue: str = "XNYS") -> SymbolData:
    """A noisy random walk with a volume spike every 60 bars (staggered by
    symbol). ``planted``: the close drifts up 0.3% a bar for 20 bars after it."""
    rng = np.random.default_rng(seed + i)
    returns = rng.normal(0, 0.005, len(DAYS))
    volume = np.full(len(DAYS), 1000.0)
    for spike in range(10 + 7 * i, len(DAYS), 60):
        volume[spike] = 5000.0
        if planted:
            returns[spike + 1 : spike + 21] += 0.003
    if not planted:  # random spikes, unrelated to what follows
        volume = np.where(rng.random(len(DAYS)) < 1 / 60, 5000.0, 1000.0)
    close = 100 * np.cumprod(1 + returns)
    rows = [(d, c, c, c, c, v) for d, c, v in zip(DAYS, close, volume, strict=True)]
    suffix = ".NS" if venue == "XNSE" else ""
    return SymbolData(f"S{i}{suffix}", venue, bars_frame(rows))


def test_grade_bands_are_the_published_thresholds() -> None:
    assert grade(MIN_EVENTS - 1, 0.05, 9.0) == "insufficient"
    assert grade(MIN_EVENTS, 0.010, 3.0) == "A"
    assert grade(MIN_EVENTS, 0.009, 3.5) == "B"  # significant but under 1%
    assert grade(MIN_EVENTS, 0.002, 2.0) == "B"
    assert grade(MIN_EVENTS, 0.002, 1.0) == "C"
    assert grade(MIN_EVENTS, 0.002, 0.99) == "D"
    assert grade(MIN_EVENTS, -0.02, -4.0) == "D"
    assert grade(MIN_EVENTS, 0.01, None) == "D"


def test_a_planted_effect_grades_a() -> None:
    datasets = [_symbol(i, planted=True, seed=1) for i in range(10)]
    result = study(datasets, SPIKE, start=START, end=END)
    assert result.n >= MIN_EVENTS
    assert result.mean_excess is not None and result.mean_excess > 0.02
    assert result.t_stat is not None and result.t_stat >= 3
    assert result.grade == "A"
    assert result.hit_rate is not None and result.hit_rate > 0.7
    assert result.fee_schedules == {"us_equity": result.n}
    assert all(START <= e.day <= END for e in result.events)


def test_noise_does_not_grade_well() -> None:
    datasets = [_symbol(i, planted=False, seed=7) for i in range(10)]
    result = study(datasets, SPIKE, start=START, end=END)
    assert result.grade in ("D", "insufficient")
    assert result.t_stat is None or abs(result.t_stat) < 2
    few = study(datasets[:1], SPIKE, start=START, end=DAYS[300])
    assert few.n < MIN_EVENTS and few.grade == "insufficient"


def test_fees_are_charged_on_the_round_trip() -> None:
    # Flat prices: the gross return is 0, so the net is exactly minus the cost.
    rows = [(d, 50.0, 50.0, 50.0, 50.0, 5000.0 if i % 60 == 30 else 1000.0)
            for i, d in enumerate(DAYS)]  # fmt: skip
    flat = SymbolData("FLAT", "XNYS", bars_frame(rows))
    result = study([flat], SPIKE, start=START, end=END)
    assert result.n > 0
    quantity = NOTIONAL / Decimal(50)
    sec_taf = US_EQUITY_2026.fees(OrderSide.SELL, quantity, Decimal(50)).total
    expected = float(sec_taf / NOTIONAL)
    assert expected > 0
    for event in result.events:
        assert event.gross == 0
        assert event.cost == pytest.approx(expected)
        assert event.net == pytest.approx(-expected)
        assert event.excess == pytest.approx(-expected)  # the base is 0 too
    # Indian delivery is far dearer: STT both ways, stamp, DP.
    nse = round_trip_cost(IN_DELIVERY_NSE_2026, 50.0, 50.0)
    assert nse > 0.002 > round_trip_cost(US_EQUITY_2026, 50.0, 50.0)
    indian = replace(flat, ticker="FLAT.NS", venue="XNSE")
    assert study([indian], SPIKE, start=START, end=END).fee_schedules == {
        "in_equity_delivery_nse": result.n
    }


def test_no_look_ahead_past_the_window() -> None:
    datasets = [_symbol(i, planted=True, seed=3) for i in range(6)]
    result = study(datasets, SPIKE, start=START, end=END)
    end_ts = pd.Timestamp(END)
    rng = np.random.default_rng(42)
    changed = []
    for data in datasets:
        bars = data.bars.copy()
        later = bars.index > end_ts
        for column in ("open", "high", "low", "close", "volume"):
            bars.loc[later, column] = bars.loc[later, column] * rng.uniform(0.2, 3.0, later.sum())
        changed.append(replace(data, bars=bars))
    again = study(changed, SPIKE, start=START, end=END)
    assert [(e.ticker, e.day, e.gross, e.base) for e in again.events] == [
        (e.ticker, e.day, e.gross, e.base) for e in result.events
    ]
    assert again.base_rate == result.base_rate
    # Every exit bar is inside the window: the last event starts 20 bars before the end.
    last_entry = max(e.day for e in result.events)
    assert DAYS.index(last_entry) + 20 <= DAYS.index(END)


def test_an_event_needs_false_before_true() -> None:
    """Unknown -> true is not an event; neither is true -> true."""
    rows = [(d, 10.0, 10.0, 10.0, 10.0, 5000.0) for d in DAYS[:200]]
    always = SymbolData("ALW", "XNYS", bars_frame(rows))
    assert study([always], SPIKE, start=DAYS[0], end=DAYS[199]).n == 0
    needs_history = compile_rule("volume > sma(volume, 50)")
    rows = [(d, 10.0, 10.0, 10.0, 10.0, 1000.0 + i) for i, d in enumerate(DAYS[:200])]
    rising = SymbolData("RIS", "XNYS", bars_frame(rows))
    # True from the first bar with 50 bars of history, after unknowns: no event.
    assert study([rising], needs_history, start=DAYS[0], end=DAYS[199]).n == 0


def test_overlapping_events_on_one_symbol_are_skipped() -> None:
    vol = [5000.0 if i % 10 == 5 else 1000.0 for i in range(400)]
    rows = [(d, 10.0, 10.0, 10.0, 10.0, v) for d, v in zip(DAYS[:400], vol, strict=True)]
    data = SymbolData("OVL", "XNYS", bars_frame(rows))
    result = study([data], SPIKE, start=DAYS[0], end=DAYS[399])
    days = [DAYS.index(e.day) for e in result.events]
    assert all(b - a >= 20 for a, b in pairwise(days))
    assert result.overlapping_skipped > 0


def test_run_evidence_stores_one_row_per_setup_and_is_idempotent(session: Session) -> None:
    seed_symbols(session, "AAA", "^GSPC")
    for i, day in enumerate(DAYS[:400]):
        c = Decimal(str(round(100 + 0.1 * i, 2)))
        session.add(
            PriceBar(
                ticker="AAA", ts=datetime.combine(day, time.min), interval="1d",
                open=c, high=c, low=c, close=c, volume=1000 + (i % 7) * 100, source="test",
            )
        )  # fmt: skip
    session.commit()
    end = DAYS[399]
    now = datetime(2026, 11, 27, 23, 0)
    run = run_evidence(session, end=end, now=now)
    assert run.end == end and (end - run.start).days == 3650
    rows = session.exec(select(ChecklistEvidence)).all()
    assert len(rows) == 7
    assert {r.dimension for r in rows} == {
        "trend", "momentum", "volume", "regime", "quality", "risk",
    }  # fmt: skip
    for row in rows:
        assert row.universe == "pinned" and row.survivorship_biased and not row.point_in_time
        assert row.window_end == end and row.horizon == 20
        assert row.grade in ("A", "B", "C", "D", "insufficient")
    india = next(r for r in rows if r.scope == "india")
    assert india.symbols == 0 and india.grade == "insufficient"
    run_evidence(session, end=end, now=now)
    assert len(session.exec(select(ChecklistEvidence)).all()) == 7
