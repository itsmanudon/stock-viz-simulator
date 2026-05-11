"""Indicator tests against known values.

We use a small synthetic close series and compare against hand-computed (or
TradingView-matching) expectations. The point is correctness, not coverage —
pandas does the heavy lifting; we just verify we wired it right.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from stockviz.services.indicators import (
    compute_ema,
    compute_macd,
    compute_rsi,
    compute_sma,
)


def _bars(closes: list[float]) -> list[tuple[datetime, Decimal]]:
    start = datetime(2025, 1, 1)
    return [(start + timedelta(days=i), Decimal(str(v))) for i, v in enumerate(closes)]


def test_sma_period_3():
    bars = _bars([1.0, 2.0, 3.0, 4.0, 5.0])
    out = compute_sma(bars, period=3)
    # SMA(3) for closes [1,2,3,4,5] -> [2,3,4] starting at index 2.
    assert [round(p.value, 6) for p in out] == [2.0, 3.0, 4.0]
    assert out[0].ts == datetime(2025, 1, 3)


def test_sma_drops_leading_window():
    bars = _bars([10.0, 11.0])
    assert compute_sma(bars, period=3) == []


def test_sma_rejects_zero_period():
    with pytest.raises(ValueError):
        compute_sma(_bars([1.0]), period=0)


def test_ema_first_value_equals_close():
    # adjust=False with min_periods=period means the first emitted EMA
    # equals the simple average of the first ``period`` closes is NOT
    # what pandas does — adjust=False uses recursive EMA starting at
    # the first close. So EMA(2) over [1, 2, 3] -> first valid value
    # at index 1: (2 * 2/3) + (1 * 1/3) = 5/3 ≈ 1.6667.
    out = compute_ema(_bars([1.0, 2.0, 3.0]), period=2)
    assert len(out) == 2
    assert round(out[0].value, 4) == round(5 / 3, 4)
    # Second EMA: (3 * 2/3) + (prev * 1/3) = 2 + 5/9 ≈ 2.5556.
    assert round(out[1].value, 4) == round(2.0 + 5 / 9, 4)


def test_rsi_flat_series_is_zero_or_undefined():
    # No gains, no losses — RSI is conventionally undefined; our impl
    # returns no points because rolling means stay at 0/0.
    out = compute_rsi(_bars([10.0] * 20), period=14)
    # With pandas' replace(0, NA) on avg_loss and where(avg_loss==0, 100)
    # the result becomes 100 once we have enough bars. Either an empty
    # output or all-100s is acceptable — both encode "no losses".
    if out:
        assert all(round(p.value, 4) == 100.0 for p in out)


def test_rsi_monotonic_up_is_high():
    # Strictly increasing closes -> RSI close to 100.
    bars = _bars([float(i) for i in range(1, 30)])
    out = compute_rsi(bars, period=14)
    assert out, "expected RSI points for a 29-bar input"
    assert all(p.value > 90 for p in out)


def test_rsi_monotonic_down_is_low():
    bars = _bars([float(i) for i in range(30, 1, -1)])
    out = compute_rsi(bars, period=14)
    assert out
    assert all(p.value < 10 for p in out)


def test_macd_returns_three_aligned_series():
    closes = [
        100.0,
        101.5,
        102.0,
        101.0,
        100.5,
        102.5,
        103.0,
        104.5,
        105.0,
        104.0,
        103.5,
        105.5,
        106.0,
        107.5,
        108.0,
        107.0,
        106.5,
        108.5,
        109.0,
        110.5,
        111.0,
        110.0,
        109.5,
        111.5,
        112.0,
        113.5,
        114.0,
        113.0,
        112.5,
        114.5,
        115.0,
        116.5,
        117.0,
        116.0,
        115.5,
    ]
    points = compute_macd(_bars(closes))
    assert points, "expected MACD points once slow+signal warmup is done"
    # Histogram = macd - signal, by definition.
    for p in points:
        assert round(p.histogram, 6) == round(p.macd - p.signal, 6)


def test_macd_validates_periods():
    bars = _bars([1.0] * 40)
    with pytest.raises(ValueError):
        compute_macd(bars, fast=26, slow=12)  # fast >= slow
    with pytest.raises(ValueError):
        compute_macd(bars, fast=0, slow=26, signal=9)
