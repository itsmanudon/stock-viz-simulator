"""Recommendation engine tests."""

from __future__ import annotations

from decimal import Decimal

from stockviz.services.recommend import (
    MAX_SCORE,
    MIN_DATA_POINTS,
    VOTE_THRESHOLD,
    score_ticker,
    votes_from_rationale,
)


def _bars(closes: list[float], volumes: list[int] | None = None):
    vols = volumes or [1_000_000] * len(closes)
    return [(Decimal(str(c)), v) for c, v in zip(closes, vols, strict=True)]


def test_score_ticker_returns_none_below_min_data():
    assert score_ticker("AAPL", _bars([100.0] * (MIN_DATA_POINTS - 1))) is None


def test_max_score_is_seven_votes():
    # Six price/volume votes plus the news-sentiment vote. The recommendations
    # UI and CLI print ``score/MAX_SCORE``; keep that denominator honest.
    assert MAX_SCORE == 7
    assert VOTE_THRESHOLD == 4


def test_uptrend_strong_buy():
    # Monotonically increasing prices with a low current close = many votes:
    # - current below mean? No (it's the highest)
    # We want a high-score case. Easier: a recent dip after a sustained rally.
    closes = [80.0, 82.0, 84.0, 86.0, 88.0, 90.0, 92.0, 94.0, 96.0, 70.0]
    volumes = [1_000_000] * 9 + [3_000_000]
    result = score_ticker("AAPL", _bars(closes, volumes))
    assert result is not None
    # Below mean, below median, within 1 stdev — 3 votes
    # Volume above average — 1 vote (5 total)
    # Recent uptrend: hist_prices last 3 are [92, 94, 96] -> strictly increasing
    # Positive slope on last 5 historical closes
    assert result.score >= VOTE_THRESHOLD
    assert result.recommend is True


def test_flat_history_low_score():
    # All prices identical -> no votes for mean/median/stdev/volume/uptrend/slope.
    result = score_ticker("AAPL", _bars([100.0] * 10))
    assert result is not None
    assert result.score == 0
    assert result.recommend is False
    assert result.rationale == []


def test_below_mean_and_median():
    closes = [120.0, 110.0, 100.0, 90.0, 80.0, 70.0, 60.0, 50.0]
    result = score_ticker("XYZ", _bars(closes))
    assert result is not None
    # Current (50) is below both mean and median of [120..60].
    rationale = " ".join(result.rationale)
    assert "Below historical mean" in rationale
    assert "Below historical median" in rationale


def test_volume_above_average_vote():
    # Static prices, but the final volume is 5x the historical average.
    closes = [100.0] * 7
    volumes = [1_000_000] * 6 + [5_000_000]
    result = score_ticker("AAPL", _bars(closes, volumes))
    assert result is not None
    assert any("Volume above average" in r for r in result.rationale)


def test_recent_uptrend_vote():
    # Strictly increasing historical prices over the last 3 bars before current.
    closes = [100.0, 99.0, 101.0, 103.0, 105.0, 105.0]
    result = score_ticker("AAPL", _bars(closes))
    assert result is not None
    assert any("uptrend" in r for r in result.rationale)


def test_positive_slope_vote():
    closes = [50.0, 60.0, 70.0, 80.0, 90.0, 100.0]
    result = score_ticker("AAPL", _bars(closes))
    assert result is not None
    assert any("Positive" in r for r in result.rationale)


def test_score_ticker_exposes_all_seven_votes():
    result = score_ticker("AAPL", _bars([100.0] * 10))
    assert result is not None
    assert [vote.id for vote in result.votes] == [
        "below_mean",
        "below_median",
        "within_one_stdev",
        "volume_above_mean",
        "recent_uptrend",
        "positive_slope",
        "positive_sentiment",
    ]
    assert result.score == sum(1 for vote in result.votes if vote.passed)
    assert result.rationale == [vote.detail for vote in result.votes if vote.passed]
    assert all(vote.passed is False for vote in result.votes)


def test_failed_votes_include_metric_detail():
    result = score_ticker("AAPL", _bars([100.0] * 10))
    assert result is not None
    by_id = {vote.id: vote for vote in result.votes}
    assert "Not below historical mean" in by_id["below_mean"].detail
    assert by_id["positive_sentiment"].detail == "No scored headlines in the trailing week"


def test_votes_from_rationale_reconstructs_pass_fail():
    votes = votes_from_rationale(
        ["Below historical mean ($70.00 < $88.00)", "3-bar uptrend (92.00 → 96.00)"]
    )
    passed = {vote.id: vote.passed for vote in votes}
    assert passed["below_mean"] is True
    assert passed["recent_uptrend"] is True
    assert passed["volume_above_mean"] is False
    assert passed["positive_sentiment"] is False
    assert len(votes) == MAX_SCORE
