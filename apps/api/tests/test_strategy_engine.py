"""A4.1: the DSL backtester's pure engine: stops, priority, sizing, R, baskets."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from stockviz.services.backtest.strategy import (
    Sizing,
    Stops,
    StrategyError,
    SymbolInput,
    run_strategy,
)
from stockviz.services.simulation import LEGACY_CLOSE, NEXT_OPEN, get_fee_schedule

NONE = get_fee_schedule("none")
START = date(2024, 1, 1)


def sym(
    bars: list[tuple[float, float, float, float]],
    entry: list[bool | None],
    exit_: list[bool | None] | None = None,
    *,
    ticker: str = "AAA",
    atr: dict[int, list[float | None]] | None = None,
    first: int = 0,
) -> SymbolInput:
    dates = [START + timedelta(days=i) for i in range(len(bars))]
    d = [[Decimal(str(v)) for v in bar] for bar in bars]
    return SymbolInput(
        ticker=ticker,
        dates=dates,
        ts=[datetime(x.year, x.month, x.day, 21, tzinfo=UTC) for x in dates],
        open=[b[0] for b in d],
        high=[b[1] for b in d],
        low=[b[2] for b in d],
        close=[b[3] for b in d],
        volume=[Decimal(1000)] * len(bars),
        entry=entry,
        exit=exit_,
        atr=atr or {},
        first=first,
    )


def run(symbols, *, stops=Stops(), sizing=Sizing(), profile=NEXT_OPEN, cash="10000", **kw):  # noqa: B008
    if isinstance(symbols, SymbolInput):
        symbols = [symbols]
    return run_strategy(
        symbols,
        initial_cash=Decimal(cash),
        stops=stops,
        sizing=sizing,
        profile=profile,
        schedule=kw.pop("schedule", NONE),
        **kw,
    )


FLAT = (100.0, 101.0, 99.0, 100.0)
SIGNAL_FIRST = [True, False, False, False, False]


def test_fixed_stop_touched_fills_at_the_stop() -> None:
    s = sym([FLAT, FLAT, (99, 100, 94, 96), FLAT, FLAT], SIGNAL_FIRST)
    r = run(s, stops=Stops(fixed_pct=5))
    (t,) = r.trades
    assert (t.entry_date, t.entry_price) == (START + timedelta(days=1), Decimal(100))
    assert t.reason == "stop_fixed" and not t.gap
    assert t.exit_price == Decimal(95) and t.exit_date == START + timedelta(days=2)
    assert t.quantity == Decimal(100)  # all in: 10000 / 100


def test_gap_through_the_stop_fills_at_the_open_and_says_so() -> None:
    s = sym([FLAT, FLAT, (90, 92, 88, 91), FLAT, FLAT], SIGNAL_FIRST)
    (t,) = run(s, stops=Stops(fixed_pct=5)).trades
    assert t.reason == "stop_fixed" and t.gap and t.exit_price == Decimal(90)


def test_atr_stop_uses_the_signal_bars_atr() -> None:
    atr = {14: [2.0, 9.0, 9.0, 9.0, 9.0]}
    s = sym([FLAT, FLAT, (99, 100, 95.5, 96), FLAT, FLAT], SIGNAL_FIRST, atr=atr)
    (t,) = run(s, stops=Stops(atr_multiple=2)).trades
    assert t.reason == "stop_atr" and t.exit_price == Decimal(96) and t.initial_stop == Decimal(96)


def test_atr_unknown_at_the_signal_skips_the_entry() -> None:
    s = sym([FLAT] * 5, SIGNAL_FIRST, atr={14: [None] * 5})
    r = run(s, stops=Stops(atr_multiple=2))
    assert r.trades == [] and r.skip_reasons == {"atr_unknown": 1}


def test_trailing_pct_ratchets_after_the_close() -> None:
    bars = [FLAT, (100, 120, 99, 118), (117, 118, 107, 110), FLAT, FLAT]
    (t,) = run(sym(bars, SIGNAL_FIRST), stops=Stops(trail_kind="pct", trail_value=10)).trades
    # Entry 100 (bar 1), high 120 -> trail 108 used from bar 2, whose low is 107.
    assert t.reason == "trail" and t.exit_price == Decimal(108)


def test_trailing_atr_uses_the_latest_close_atr() -> None:
    atr = {5: [1.0, 2.0, 2.0, 2.0, 2.0]}
    bars = [FLAT, (100, 110, 99, 109), (108, 108, 105, 106), FLAT, FLAT]
    stops = Stops(trail_kind="atr", trail_value=2, trail_period=5)
    (t,) = run(sym(bars, SIGNAL_FIRST, atr=atr), stops=stops).trades
    assert t.exit_price == Decimal(106) and t.reason == "trail"  # 110 - 2 x 2


def test_time_stop_exits_after_n_closes() -> None:
    (t,) = run(sym([FLAT] * 6, [True] + [False] * 5), stops=Stops(time_bars=2)).trades
    assert t.reason == "time" and t.bars_held == 2
    assert t.exit_date == START + timedelta(days=3)  # held bars 1 and 2, out at bar 3's open


def test_exit_rule_fills_on_the_next_bar() -> None:
    s = sym([FLAT, FLAT, FLAT, (105, 106, 104, 105), FLAT], SIGNAL_FIRST,
            [False, False, True, False, False])  # fmt: skip
    (t,) = run(s).trades
    assert t.reason == "exit_rule" and t.exit_price == Decimal(105)


def test_same_bar_priority_nearest_stop_wins() -> None:
    atr = {14: [1.5, 1.5, 1.5, 1.5, 1.5]}
    s = sym([FLAT, FLAT, (99, 100, 90, 92), FLAT, FLAT], SIGNAL_FIRST, atr=atr)
    (t,) = run(s, stops=Stops(fixed_pct=5, atr_multiple=2)).trades
    assert t.reason == "stop_atr" and t.exit_price == Decimal(97)  # 97 > 95: hit first


def test_priority_ties_go_to_the_fixed_stop() -> None:
    atr = {14: [2.5] * 5}
    s = sym([FLAT, FLAT, (99, 100, 90, 92), FLAT, FLAT], SIGNAL_FIRST, atr=atr)
    (t,) = run(s, stops=Stops(fixed_pct=5, atr_multiple=2)).trades
    assert t.reason == "stop_fixed" and t.exit_price == Decimal(95)


def test_pending_exit_at_the_open_beats_an_intrabar_stop() -> None:
    s = sym([FLAT, FLAT, (99, 100, 90, 92), FLAT, FLAT], SIGNAL_FIRST,
            [False, True, False, False, False])  # fmt: skip
    (t,) = run(s, stops=Stops(fixed_pct=5)).trades
    assert t.reason == "exit_rule" and t.exit_price == Decimal(99)


def test_a_gap_beats_a_pending_exit_at_the_open() -> None:
    s = sym([FLAT, FLAT, (90, 92, 88, 91), FLAT, FLAT], SIGNAL_FIRST,
            [False, True, False, False, False])  # fmt: skip
    (t,) = run(s, stops=Stops(fixed_pct=5)).trades
    assert t.reason == "stop_fixed" and t.gap and t.exit_price == Decimal(90)


def test_next_close_intrabar_stop_beats_the_close_exit() -> None:
    s = sym([FLAT, FLAT, FLAT, (99, 100, 90, 92), FLAT], SIGNAL_FIRST,
            [False, False, True, False, False])  # fmt: skip
    (t,) = run(s, stops=Stops(fixed_pct=5), profile=LEGACY_CLOSE).trades
    # Entered at bar 1's close (100); the exit order for bar 3's close loses to the stop.
    assert t.reason == "stop_fixed" and t.exit_price == Decimal(95)


def test_next_close_exit_fills_at_the_close() -> None:
    s = sym([FLAT, FLAT, FLAT, (99, 103, 98, 102), FLAT], SIGNAL_FIRST,
            [False, False, True, False, False])  # fmt: skip
    (t,) = run(s, profile=LEGACY_CLOSE).trades
    assert t.reason == "exit_rule" and t.exit_price == Decimal(102)


def test_next_open_entry_bar_can_hit_the_stop() -> None:
    s = sym([FLAT, (100, 101, 94, 95), FLAT, FLAT], [True, False, False, False])
    (t,) = run(s, stops=Stops(fixed_pct=5)).trades
    assert t.entry_date == t.exit_date and t.exit_price == Decimal(95)


def test_fixed_fraction_sizing() -> None:
    (t,) = run(sym([FLAT] * 3, [True, False, False]), sizing=Sizing("fixed_fraction", 0.25)).trades
    assert t.quantity == Decimal(25) and t.open and t.reason == "end_of_data"


def test_fixed_risk_sizing_and_r_multiple() -> None:
    s = sym([FLAT, FLAT, (99, 100, 94, 96), FLAT, FLAT], SIGNAL_FIRST)
    r = run(s, stops=Stops(fixed_pct=5), sizing=Sizing("fixed_risk", risk_pct=1))
    (t,) = r.trades
    assert t.quantity == Decimal(20)  # 1% of 10000 = 100 at risk, 5 a share
    assert t.initial_risk == Decimal(100) and t.pnl == Decimal(-100) and t.r_multiple == -1.0


def test_fixed_risk_needs_a_price_stop() -> None:
    with pytest.raises(StrategyError):
        run(sym([FLAT] * 3, [True, False, False]), sizing=Sizing("fixed_risk", risk_pct=1))


def test_r_is_net_of_fees() -> None:
    s = sym([FLAT, FLAT, (99, 100, 94, 96), FLAT, FLAT], SIGNAL_FIRST)
    (t,) = run(
        s,
        stops=Stops(fixed_pct=5),
        sizing=Sizing("fixed_risk", risk_pct=1),
        commission_bps=Decimal(10),
    ).trades
    assert t.pnl == Decimal(-100) - t.entry_fees - t.exit_fees
    assert t.r_multiple is not None and t.r_multiple < -1.0


def test_basket_max_positions_takes_entries_in_universe_order() -> None:
    a = sym([FLAT] * 4, [True, False, False, False], ticker="AAA")
    b = sym([FLAT] * 4, [True, False, False, False], ticker="BBB")
    r = run([a, b], sizing=Sizing(max_positions=1))
    assert [t.ticker for t in r.trades] == ["AAA"] and r.skip_reasons == {"no_slot": 1}


def test_basket_all_in_splits_cash_over_free_slots() -> None:
    a = sym([FLAT] * 4, [True, False, False, False], ticker="AAA")
    b = sym([FLAT] * 4, [True, False, False, False], ticker="BBB")
    r = run([a, b])
    assert [t.quantity for t in r.trades] == [Decimal(50), Decimal(50)]


def test_unknown_signals_do_nothing_and_are_counted() -> None:
    s = sym([FLAT] * 5, [None, None, True, False, False], [None, None, None, None, None])
    r = run(s)
    (t,) = r.trades
    assert r.symbols[0].unknown_entry_bars == 2
    assert r.symbols[0].unknown_exit_bars == 1  # bar 3: held, exit unknown (bar 4 is last)
    assert t.entry_date == START + timedelta(days=3)


def test_entries_while_held_are_ignored() -> None:
    r = run(sym([FLAT] * 5, [True, True, True, False, False]))
    assert len(r.trades) == 1 and r.ignored_entry_signals == 2


def test_warmup_bars_are_not_traded_but_the_last_one_signals() -> None:
    s = sym([FLAT] * 5, [True, False, True, False, False], first=2)
    r = run(s)
    (t,) = r.trades
    assert t.entry_date == START + timedelta(days=3)  # signal on bar 2 (first window bar)
    assert r.equity_curve[0][0] == START + timedelta(days=2)
    s = sym([FLAT] * 5, [False, True, False, False, False], first=2)
    (t,) = run(s).trades
    assert t.entry_date == START + timedelta(days=2)  # signal on the last warm-up bar


def test_short_stop_and_pnl() -> None:
    s = sym([FLAT, FLAT, (101, 106, 100, 104), FLAT, FLAT], SIGNAL_FIRST)
    r = run(s, stops=Stops(fixed_pct=5), short=True)
    (t,) = r.trades
    assert t.direction == "short" and t.exit_price == Decimal(105) and t.reason == "stop_fixed"
    assert t.pnl == Decimal(-500) and r.final_nav == Decimal(9500)


def test_short_gap_up_fills_at_the_open() -> None:
    s = sym([FLAT, FLAT, (110, 112, 108, 111), FLAT, FLAT], SIGNAL_FIRST)
    (t,) = run(s, stops=Stops(fixed_pct=5), short=True).trades
    assert t.gap and t.exit_price == Decimal(110)


def test_gross_adds_costs_back() -> None:
    s = sym([FLAT, FLAT, FLAT, FLAT, FLAT], SIGNAL_FIRST, [False, False, True, False, False])
    from stockviz.services.simulation import CostModel

    r = run(s, costs=CostModel(spread_bps=Decimal(20)), commission_bps=Decimal(5))
    assert r.final_nav < Decimal(10000)
    assert r.gross_final_nav == r.final_nav + r.total_fees + r.price_costs
    assert r.price_costs > 0 and r.total_fees > 0


def test_no_look_ahead_in_the_engine() -> None:
    bars = [FLAT, FLAT, (99, 100, 94, 96), FLAT, FLAT, FLAT, FLAT, FLAT]
    entry = [True, False, False, True, False, False, False, False]
    base = run(sym(bars, entry), stops=Stops(fixed_pct=5)).trades
    later = bars[:5] + [(50, 51, 1, 2)] * 3
    perturbed = run(sym(later, entry), stops=Stops(fixed_pct=5)).trades
    assert [t for t in base if t.exit_date < START + timedelta(days=5)] == [
        t for t in perturbed if t.exit_date < START + timedelta(days=5)
    ]
