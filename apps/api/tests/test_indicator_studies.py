"""A3.4 (M2.6): reference tests for the studies added to the registry.

Two kinds of reference, named on each test:

- **Published worked examples.** StockCharts ChartSchool publishes a
  spreadsheet with each indicator article. The inputs and the published
  values are copied (only the columns needed) into
  ``tests/fixtures/indicators/*.csv``, read 26 Nov 2026 from the article's
  linked ``cs-*.xls``:

  - ``cmf.csv``: "Chaikin Money Flow (CMF)" (cs-cmf.xls)
  - ``kama.csv``: "Kaufman's Adaptive Moving Average (KAMA)"
  - ``tsi.csv``: "True Strength Index" (sheet "TSI 500")
  - ``ultimate.csv``: "Ultimate Oscillator"
  - ``vortex.csv``: "Vortex Indicator"
  - ``stochrsi.csv``: "StochRSI" (RSI given; StockCharts' scale is 0-1)
  - ``price_relative.csv``: "Price Relative / Relative Strength"
  - ``mass_index.csv``: "Mass Index" (sheet "504 periods")
  - ``coppock.csv``: "Coppock Curve" (monthly closes)
  - ``emv.csv``: "Ease of Movement (EMV)"
  - ``ppo.csv``: "Percentage Price Oscillator (PPO)"

- **Hand-worked small cases** where no public worked example exists
  (Ichimoku, Hull MA, DEMA, TEMA, Parabolic SAR, pivots, ATR %, RMV, Aroon,
  choppiness, Elder ray, Chande momentum, force index, TRIX). The arithmetic
  is written beside each expected value.

Then every new study is checked for warm-up (a value inside the window does
not depend on where the loaded data starts) and for bounds.
"""

# pyright: reportArgumentType=false, reportAttributeAccessIssue=false, reportIndexIssue=false

from __future__ import annotations

import csv
import math
import random
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from stockviz.services.indicators import engine

FIXTURES = Path(__file__).parent / "fixtures" / "indicators"
NEW = [
    "ichimoku",
    "hma",
    "kama",
    "psar",
    "cmf",
    "tsi",
    "natr",
    "pivots",
    "rmv",
    "rsline",
    "dema",
    "tema",
    "aroon",
    "vortex",
    "uo",
    "chop",
    "elder",
    "stochrsi",
    "chaikin",
    "trix",
    "ppo",
    "cmo",
    "force",
    "eom",
    "massi",
    "coppock",
]


def _rows(name: str) -> list[dict[str, str]]:
    with (FIXTURES / f"{name}.csv").open() as fh:
        return [r for r in csv.DictReader(fh) if any(v for k, v in r.items() if k != "date")]


def _frame(rows: list[dict[str, str]]) -> pd.DataFrame:
    index = pd.DatetimeIndex([r["date"] for r in rows])
    data = {}
    for col in ("open", "high", "low", "close", "volume"):
        if col in rows[0]:
            data[col] = [float(r[col]) if r[col] else np.nan for r in rows]
    f = pd.DataFrame(data, index=index, dtype=float)
    for col in ("open", "high", "low", "close", "volume"):
        if col not in f:
            f[col] = f["close"] if "close" in f else f["high"]
    return f


def _expected(rows: list[dict[str, str]], col: str) -> list[float | None]:
    return [float(r[col]) if r[col] else None for r in rows]


def _match(got: pd.Series, expected: list[float | None], *, tol=1e-9, abs_tol=0.0, last=None):
    values = got.tolist()
    assert len(values) == len(expected)
    checked = 0
    start = len(expected) - last if last else 0
    for i, (g, e) in enumerate(zip(values, expected, strict=True)):
        if e is None or i < start:
            continue
        checked += 1
        assert not math.isnan(g), f"row {i}: missing, expected {e}"
        assert abs(g - e) <= max(tol * max(1.0, abs(e)), abs_tol), f"row {i}: {g} != {e}"
    assert checked > 0
    return checked


def _hand(rows: list[tuple[float, float, float, float]]) -> pd.DataFrame:
    """(high, low, close, volume) rows on consecutive business days."""
    index = pd.bdate_range("2024-01-01", periods=len(rows))
    h, lo, c, v = zip(*rows, strict=True)
    return pd.DataFrame(
        {"open": c, "high": h, "low": lo, "close": c, "volume": v}, index=index, dtype=float
    )


def _closes(values: list[float], volume: float = 100) -> pd.DataFrame:
    return _hand([(c, c, c, volume) for c in values])


def _vals(series: pd.Series) -> list[float | None]:
    return [None if math.isnan(x) else round(float(x), 6) for x in series.tolist()]


# --- published worked examples (StockCharts ChartSchool) -----------------------


def test_cmf_matches_stockcharts() -> None:
    rows = _rows("cmf")
    assert _match(engine.cmf(_frame(rows), 20)["value"], _expected(rows, "cmf20")) == 11


def test_ad_line_is_the_running_sum_of_stockcharts_money_flow_volume() -> None:
    rows = _rows("cmf")
    expected = np.cumsum([float(r["mf_volume"]) for r in rows])
    _match(engine.ad(_frame(rows))["value"], list(expected), tol=1e-9)


def test_kama_matches_stockcharts() -> None:
    rows = _rows("kama")
    assert (
        _match(engine.kama(_frame(rows), 10, 2, 30)["value"], _expected(rows, "kama_10_2_30")) == 40
    )


def test_tsi_matches_stockcharts_after_warm_up() -> None:
    # The sheet rounds its EMA multipliers to four places (2/26 -> 0.0769,
    # 2/14 -> 0.1429) and seeds each EMA with an SMA, so values agree to a few
    # hundredths of a TSI point once both have warmed up (the last 300 rows).
    rows = _rows("tsi")
    got = engine.tsi(_frame(rows), 25, 13, 7)["tsi"]
    assert _match(got, _expected(rows, "tsi_25_13"), tol=0, abs_tol=0.02, last=300) == 300


def test_ultimate_oscillator_matches_stockcharts() -> None:
    rows = _rows("ultimate")
    assert _match(engine.uo(_frame(rows), 7, 14, 28)["value"], _expected(rows, "uo_7_14_28")) == 2


def test_vortex_matches_stockcharts() -> None:
    rows = _rows("vortex")
    out = engine.vortex(_frame(rows), 14)
    assert _match(out["plus"], _expected(rows, "plus_vi14")) == 16
    assert _match(out["minus"], _expected(rows, "minus_vi14")) == 16


def test_stochrsi_matches_stockcharts_on_its_rsi() -> None:
    rows = _rows("stochrsi")
    rsi = pd.Series([float(r["rsi14"]) for r in rows])
    # StockCharts shows 0-1; the registry's study is 0-100.
    expected = [None if e is None else 100 * e for e in _expected(rows, "stochrsi14")]
    assert _match(engine.stoch_of(rsi, 14), expected) == 17


def test_stochrsi_smoothing_is_k_then_d() -> None:
    f = _closes([100 + 3 * math.sin(i / 3) + i * 0.1 for i in range(120)])
    raw = engine.stoch_of(engine.rsi(f, 14)["value"], 14)
    out = engine.stochrsi(f, 14, 14, 3, 3)
    pd.testing.assert_series_equal(out["k"], raw.rolling(3, min_periods=3).mean())
    pd.testing.assert_series_equal(out["d"], out["k"].rolling(3, min_periods=3).mean())
    pd.testing.assert_series_equal(engine.stochrsi(f, 14, 14, 1, 1)["k"], raw)


def test_rs_line_matches_stockcharts_price_relative() -> None:
    rows = _rows("price_relative")
    f = _frame(rows)
    f["bench"] = [float(r["bench_close"]) for r in rows]
    assert _match(engine.rsline(f)["value"], _expected(rows, "price_relative")) == 30
    assert engine.rsline(f.drop(columns="bench"))["value"].isna().all()


def test_mass_index_matches_stockcharts_after_warm_up() -> None:
    rows = _rows("mass_index")
    got = engine.massi(_frame(rows), 9, 25)["value"]
    assert _match(got, _expected(rows, "mass_9_25"), tol=1e-9, last=300) == 300


def test_coppock_matches_stockcharts_monthly() -> None:
    rows = _rows("coppock")
    got = engine.coppock(_frame(rows), 14, 11, 10)["value"]
    assert _match(got, _expected(rows, "coppock_14_11_10")) == 9


def test_ease_of_movement_matches_stockcharts() -> None:
    rows = _rows("emv")
    assert _match(engine.eom(_frame(rows), 14)["value"], _expected(rows, "emv_sma14")) == 16


def test_ppo_matches_stockcharts_formula() -> None:
    # The sheet starts with its EMAs already running, so its PPO column is
    # checked against its own EMAs, and the study against the same formula.
    for r in _rows("ppo"):
        ema12, ema26 = float(r["ema12"]), float(r["ema26"])
        assert 100 * (ema12 - ema26) / ema26 == pytest.approx(float(r["ppo"]), abs=1e-9)
    f = _closes([50 + 5 * math.sin(i / 7) for i in range(200)])
    out = engine.ppo(f, 12, 26, 9)
    slow = f["close"].ewm(span=26, adjust=False, min_periods=26).mean()
    macd = engine.macd(f, 12, 26, 9)["macd"]
    pd.testing.assert_series_equal(out["ppo"], 100 * macd / slow, check_names=False)


# --- hand-worked cases ---------------------------------------------------------


def test_ichimoku_hand_case_and_displacement() -> None:
    highs = [10, 12, 11, 13, 15, 14, 16, 15]
    lows = [8, 9, 9, 10, 12, 12, 13, 13]
    f = _hand([(h, lo, (h + lo) / 2, 100) for h, lo in zip(highs, lows, strict=True)])
    out = engine.ichimoku(f, 2, 3, 4, 2)
    # tenkan(2) = (2-bar high + 2-bar low) / 2: bar 1 (12 + 8) / 2 = 10, ...
    assert _vals(out["tenkan"]) == [None, 10, 10.5, 11, 12.5, 13.5, 14, 14.5]
    # kijun(3): bar 2 (12 + 8) / 2 = 10, bar 3 (13 + 9) / 2 = 11, ...
    assert _vals(out["kijun"]) == [None, None, 10, 11, 12, 12.5, 14, 14]
    # senkou A computed on bar 2 = (10.5 + 10) / 2 = 10.25, drawn on bar 4.
    assert _vals(out["senkou_a"]) == [None, None, None, None, 10.25, 11, 12.25, 13]
    # senkou B(4) computed on bar 3 = (13 + 8) / 2 = 10.5, drawn on bar 5.
    assert _vals(out["senkou_b"]) == [None, None, None, None, None, 10.5, 12, 12]
    # The cloud on bar 7 comes from bars up to 5: changing bars 6 and 7 leaves it.
    moved = f.copy()
    moved.iloc[6:, :] = [[1, 99, 1, 1, 1]] * 2
    again = engine.ichimoku(moved, 2, 3, 4, 2)
    assert again["senkou_a"].iloc[7] == 13 and again["senkou_b"].iloc[7] == 12


def test_hull_ma_hand_case() -> None:
    # n = 4: WMA(2) and WMA(4), then WMA(2) of 2 WMA(2) - WMA(4).
    # raw bar 3 = 2 x 11/3 - 3 = 13/3; bar 4 = 2 x 14/3 - 4 = 16/3;
    # bar 5 = 2 x 19/3 - 5.4 = 109/15. HMA bar 4 = (13/3 + 2 x 16/3) / 3 = 5;
    # bar 5 = (16/3 + 2 x 109/15) / 3 = 298/45.
    out = engine.hma(_closes([1, 2, 3, 4, 5, 7]), 4)["value"]
    assert _vals(out)[:4] == [None] * 4
    assert out.iloc[4] == pytest.approx(5)
    assert out.iloc[5] == pytest.approx(298 / 45)


def test_dema_tema_hand_case() -> None:
    # n = 3: EMA alpha 0.5 started on the first value, shown after 3 values.
    # E1 = 2, 3, 4.5, 6.25, 8.125, 10.0625, 12.03125 on closes 2, 4, ..., 14.
    # E2 (of E1 from bar 2) = 6.75, 8.40625, 10.21875 on bars 4-6;
    # E3 (of E2 from bar 4) = 8.8984375 on bar 6.
    f = _closes([2, 4, 6, 8, 10, 12, 14])
    dema = engine.dema(f, 3)["value"]
    assert _vals(dema)[:4] == [None] * 4
    assert dema.iloc[4] == pytest.approx(2 * 8.125 - 6.75)
    assert dema.iloc[6] == pytest.approx(2 * 12.03125 - 10.21875)
    tema = engine.tema(f, 3)["value"]
    assert _vals(tema)[:6] == [None] * 6
    assert tema.iloc[6] == pytest.approx(3 * 12.03125 - 3 * 10.21875 + 8.8984375)


def test_parabolic_sar_hand_case() -> None:
    # step 0.02, max 0.2. Close 1 >= close 0: long, SAR 9 (low 0), EP 10.
    # Bar 1: EP 11, AF .04, next 9 + .04 x 2 = 9.08, capped at low 0 = 9.
    # Bar 2: EP 12, AF .06, next 9 + .06 x 3 = 9.18.
    # Bar 3: EP 12.5, AF .08, next 9.18 + .08 x 3.32 = 9.4456.
    # Bar 4: low 9.2 < 9.4456: short, SAR = EP 12.5, EP 9.2, AF .02.
    # Bar 5: EP 9, AF .04, next 12.5 + .04 x (9 - 12.5) = 12.36.
    # Bar 6: high 13 > 12.36: long again.
    f = _hand([(10, 9, 9.5, 1), (11, 9.5, 10.5, 1), (12, 10.5, 11.5, 1), (12.5, 11, 12, 1),
               (12, 9.2, 9.5, 1), (11, 9, 9.3, 1), (13, 10, 12.8, 1)])  # fmt: skip
    out = engine.psar(f, 0.02, 0.2)
    assert _vals(out["sar"]) == [None, 9, 9, 9.18, 9.4456, 12.5, 12.36]
    assert _vals(out["direction"]) == [None, 1, 1, 1, -1, -1, 1]


def test_pivots_hand_cases() -> None:
    # Prior bar: H 12, L 8, C 10 -> PP 10, R1 2x10-8 = 12, S1 8, R2 10+4 = 14, S2 6.
    out = engine.pivots(_hand([(12, 8, 10, 1), (11, 9, 10, 1)]), 1)
    assert [out[k].iloc[1] for k in ("pp", "r1", "s1", "r2", "s2")] == [10, 12, 8, 14, 6]
    # Prior month: January (may be partial) gives February nothing; March
    # uses February's high, low and last close.
    days = pd.bdate_range("2024-01-15", "2024-03-29")
    rng = random.Random(3)
    closes = [100 + rng.uniform(-5, 5) for _ in days]
    f = pd.DataFrame(
        {"open": closes, "high": [c + 1 for c in closes], "low": [c - 1 for c in closes],
         "close": closes, "volume": 1.0}, index=days,
    )  # fmt: skip
    out = engine.pivots(f, 3)
    feb = f[f.index.month == 2]
    h, lo, c = feb["high"].max(), feb["low"].min(), feb["close"].iloc[-1]
    pp = (h + lo + c) / 3
    march = f.index.month == 3
    assert out["pp"][~march].isna().all()
    assert np.allclose(out["pp"][march], pp) and np.allclose(out["r2"][march], pp + h - lo)


def test_natr_hand_case() -> None:
    # A steady 2-point range on a 10 close: ATR 2, ATR % = 20.
    out = engine.natr(_hand([(11, 9, 10, 1)] * 30), 14)["value"]
    assert out.iloc[-1] == pytest.approx(20)


def test_rmv_hand_case() -> None:
    # n = 2, lookback 3. 2-bar range % of close: bar 1 (11-9)/11 = 18.18,
    # bar 2 (11.5-10)/11 = 13.64, bar 3 (12-11)/12 = 8.33, bar 4 (14-11)/12 = 25,
    # bar 5 (14-11)/12.5 = 24. Bar 3 is the low of [18.18, 13.64, 8.33]: 0;
    # bar 4 the high of [13.64, 8.33, 25]: 100; bar 5 (24-8.33)/(25-8.33) = 94.
    f = _hand([(10, 9, 10, 1), (11, 10, 11, 1), (11.5, 11, 11, 1), (12, 11.5, 12, 1),
               (14, 11, 12, 1), (13, 12, 12.5, 1)])  # fmt: skip
    out = engine.rmv(f, 2, 3)["value"]
    assert _vals(out)[:3] == [None] * 3
    assert out.iloc[3] == pytest.approx(0)
    assert out.iloc[4] == pytest.approx(100)
    assert out.iloc[5] == pytest.approx(94)


def test_aroon_hand_case() -> None:
    # n = 3, over the bar and the 3 before it; ties go to the most recent.
    f = _hand([(1, 5, 1, 1), (3, 4, 1, 1), (2, 4, 1, 1), (2, 6, 1, 1), (1, 7, 1, 1),
               (0, 3, 1, 1)])  # fmt: skip
    out = engine.aroon(f, 3)
    # Bar 3: high 3 two bars back -> 100 x (3-2)/3; bar 4: 3 bars back -> 0;
    # bar 5: 2 and 2 tie, the later is 2 back -> 33.3.
    assert _vals(out["up"])[3:] == [round(100 / 3, 6), 0, round(100 / 3, 6)]
    # Lows: bar 3 low 4 one bar back -> 66.7; bar 5 low 3 today -> 100.
    assert out["down"].iloc[3] == pytest.approx(200 / 3)
    assert out["down"].iloc[5] == 100


def test_choppiness_hand_case() -> None:
    # n = 2: true ranges 2 and 2 (sum 4) over a range of 12 - 9 = 3.
    f = _hand([(10, 8, 9, 1), (11, 9, 10, 1), (12, 10, 11, 1)])
    out = engine.chop(f, 2)["value"]
    assert out.iloc[2] == pytest.approx(100 * math.log10(4 / 3) / math.log10(2))
    assert math.isnan(out.iloc[1])  # bar 0 has no true range (no prior close)


def test_elder_ray_hand_case() -> None:
    # EMA(3) of 2, 4, 6, 8 = 6.25 on bar 3; high 9 -> 2.75, low 7 -> 0.75.
    f = _hand([(2, 2, 2, 1), (4, 4, 4, 1), (6, 6, 6, 1), (9, 7, 8, 1)])
    out = engine.elder(f, 3)
    assert out["bull"].iloc[3] == pytest.approx(2.75)
    assert out["bear"].iloc[3] == pytest.approx(0.75)


def test_cmo_force_trix_hand_cases() -> None:
    # CMO(2) on 10, 11, 10.5, 12: changes +1, -0.5, +1.5.
    cmo = engine.cmo(_closes([10, 11, 10.5, 12]), 2)["value"]
    assert cmo.iloc[2] == pytest.approx(100 * (1 - 0.5) / 1.5)
    assert cmo.iloc[3] == pytest.approx(100 * (1.5 - 0.5) / 2)
    # Force(2): (change x volume) 100, 400, -100; EMA alpha 2/3 -> 300, 33.3.
    f = _hand([(10, 10, 10, 100), (11, 11, 11, 100), (13, 13, 13, 200), (12, 12, 12, 100)])
    force = engine.force(f, 2)["value"]
    assert force.iloc[2] == pytest.approx(300)
    assert force.iloc[3] == pytest.approx(100 / 3)
    # TRIX(1) is the one-bar percent change: 100 -> 110 is 10%.
    assert engine.trix(_closes([100, 110]), 1)["value"].iloc[1] == pytest.approx(10)


def test_chaikin_oscillator_ignores_the_line_starting_level() -> None:
    rows = _rows("cmf")
    f = _frame(rows)
    out = engine.chaikin(f, 3, 10)["value"]
    line = engine.ad(f)["value"]
    ema = lambda s, n: s.ewm(span=n, adjust=False, min_periods=n).mean()  # noqa: E731
    want = ema(line, 3) - ema(line, 10)
    _match(out, [None if math.isnan(x) else x for x in want], tol=1e-9)
    shifted = ema(line + 1e6, 3) - ema(line + 1e6, 10)
    assert np.allclose(out.dropna(), shifted.dropna(), atol=1e-6)


# --- warm-up, bounds, registry shape -------------------------------------------


def _random_frame(n: int = 2600, seed: int = 5) -> pd.DataFrame:
    rng = random.Random(seed)
    rows, price = [], 100.0
    for _ in range(n):
        o = price
        c = max(1.0, o * (1 + rng.gauss(0, 0.02)))
        rows.append((max(o, c) * 1.01, min(o, c) * 0.99, c, rng.randint(1_000, 50_000)))
        price = c
    f = _hand(rows)
    f["bench"] = f["close"].rolling(5, min_periods=1).mean()
    return f


@pytest.mark.parametrize("key", NEW)
def test_new_study_warm_up_makes_the_window_independent_of_the_start(key: str) -> None:
    """RS-1 for each new study: computed from ``lookback`` bars before the
    window, the window's values equal those computed from far earlier."""
    f = _random_frame()
    req = engine.parse(engine.REGISTRY[key].default_key())
    window = 40
    start = len(f) - window - req.lookback
    assert start > 0
    full = engine.compute(req, f)
    short = engine.compute(req, f.iloc[start:])
    for name, values in full.items():
        a = values.iloc[-window:].to_numpy()
        b = short[name].iloc[-window:].to_numpy()
        # The engine's warm-up rule: the start contributes under 0.01% of the
        # series' scale.
        scale = max(1.0, float(np.nanmax(np.abs(a))))
        assert np.array_equal(np.isnan(a), np.isnan(b)), (key, name)
        assert np.nanmax(np.abs(a - b)) <= 1e-4 * scale, (key, name)
        assert not np.isnan(b).all(), (key, name)


def test_registry_has_about_45_studies_with_parameter_schemas() -> None:
    assert len(engine.REGISTRY) >= 45
    assert set(NEW) <= set(engine.REGISTRY)
    for spec in engine.REGISTRY.values():
        assert engine.parse(spec.default_key()).args == tuple(spec.defaults)
        for p in spec.parameters:
            assert p.lo <= p.default <= p.hi, (spec.key, p.name)
        # The largest parameters still fit the API's warm-up cap.
        top = [int(p.hi) if p.integer else p.hi for p in spec.parameters]
        assert spec.lookback(*top) <= 5000, spec.key


@pytest.mark.parametrize(
    "token",
    ["psar_0_0.2", "psar_0.02_2", "ichimoku_9_26_52_0", "pivots_5", "kama_10_2_99",
     "hma_1", "tsi_25_13_7_1", "rmv_5_1", "dema_301"],
)  # fmt: skip
def test_parameter_bounds_are_enforced(token: str) -> None:
    with pytest.raises(ValueError):
        engine.parse(token)


def test_parameter_values_parse() -> None:
    assert engine.parse("psar_0.03_0.25").args == (0.03, 0.25)
    assert engine.parse("rsi_21").args == (21,)
    assert engine.parse("pivots_1").args == (1,)
    assert engine.REGISTRY["pivots"].parameters[0].schema()["choices"] == [
        "bar", "week", "month", "year",
    ]  # fmt: skip
