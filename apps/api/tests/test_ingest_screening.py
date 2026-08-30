"""Pure-logic tests for plausibility screening of ingested price bars (F-011).

``screen_bar`` takes a single :class:`BarRecord` (and an optional prior close)
and returns a :class:`Verdict` — no DB, no network.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from stockviz.services.ingest.prices import DAILY_INTERVAL, SOURCE_YFINANCE, BarRecord
from stockviz.services.ingest.screening import Disposition, screen_bar


def _bar(
    *,
    open: str = "100",
    high: str = "101",
    low: str = "99",
    close: str = "100.5",
    volume: int = 1_000_000,
) -> BarRecord:
    return BarRecord(
        ticker="AAPL",
        ts=datetime(2025, 4, 10),
        interval=DAILY_INTERVAL,
        open=Decimal(open),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        volume=volume,
        source=SOURCE_YFINANCE,
    )


def test_accepts_an_ordinary_bar():
    assert screen_bar(_bar()).disposition is Disposition.ACCEPT


def test_rejects_a_negative_close():
    verdict = screen_bar(_bar(open="100", high="101", low="0.01", close="-100.5"))
    assert verdict.disposition is Disposition.REJECT
    assert "close" in verdict.reason and "positive" in verdict.reason


def test_rejects_a_zero_open():
    assert screen_bar(_bar(open="0", low="0")).disposition is Disposition.REJECT


def test_rejects_a_non_finite_price():
    # yfinance uses NaN for a missing field; Decimal(str(nan)) == Decimal("NaN").
    assert screen_bar(_bar(high="NaN")).disposition is Disposition.REJECT


def test_rejects_low_above_high():
    assert screen_bar(_bar(low="102", high="101")).disposition is Disposition.REJECT


def test_rejects_open_outside_the_low_high_band():
    assert screen_bar(_bar(open="105")).disposition is Disposition.REJECT


def test_rejects_close_outside_the_low_high_band():
    assert screen_bar(_bar(close="98")).disposition is Disposition.REJECT


def test_rejects_negative_volume():
    assert screen_bar(_bar(volume=-1)).disposition is Disposition.REJECT


def test_allows_zero_volume():
    assert screen_bar(_bar(volume=0)).disposition is Disposition.ACCEPT


def test_quarantines_an_implausible_intrabar_range():
    verdict = screen_bar(_bar(low="100", high="181", open="100", close="180"))
    assert verdict.disposition is Disposition.QUARANTINE
    assert "range" in verdict.reason


def test_accepts_a_large_but_plausible_intrabar_range():
    # 40% high/low spread — wide, but real names do this on event days.
    assert screen_bar(_bar(low="100", high="140", open="105", close="138")).disposition is (
        Disposition.ACCEPT
    )


def test_quarantines_a_day_over_day_move_past_the_threshold():
    verdict = screen_bar(_bar(close="100.5"), prev_close=Decimal("40"))
    assert verdict.disposition is Disposition.QUARANTINE
    assert "prior close" in verdict.reason


def test_accepts_a_day_over_day_move_within_the_threshold():
    verdict = screen_bar(
        _bar(open="150", high="151", low="149", close="150"), prev_close=Decimal("100")
    )
    assert verdict.disposition is Disposition.ACCEPT


def test_skips_the_day_over_day_check_when_no_prior_close_is_known():
    verdict = screen_bar(_bar(open="150", high="151", low="149", close="150"), prev_close=None)
    assert verdict.disposition is Disposition.ACCEPT
