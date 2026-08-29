"""7-vote recommendation engine over ``PriceBar`` rows.

Pure function ``score_ticker(bars)`` takes the bar series and returns a
``RecommendationResult`` with the integer score (0..MAX_SCORE), the boolean
``recommend`` flag, per-vote rationale strings, and structured ``votes`` so
the Signals workspace can show pass/fail evidence without re-running the
algo. ``score_universe`` iterates every active symbol in the DB and writes
the latest result into the ``recommendations`` table so the API can serve
it without re-running the algo per request.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

import numpy as np
from sqlmodel import Session, select

from stockviz._time import utcnow
from stockviz.models import PriceBar, Recommendation, Symbol, SymbolMetrics

logger = logging.getLogger(__name__)

MIN_DATA_POINTS = 6
"""Below this we can't compute a meaningful score — current + 5 historical."""

VOTE_THRESHOLD = 4
"""``score >= VOTE_THRESHOLD`` flips ``recommend`` to True."""

MAX_SCORE = 7
"""Six price/volume votes plus the news-sentiment vote."""

SENTIMENT_VOTE_THRESHOLD = 0.2
"""Trailing-week mean sentiment above this counts as a vote in favour.

Set above the neutral band so a mildly-positive average doesn't tip the score;
a symbol with no scored news simply doesn't get the vote, rather than being
penalised for it."""

TREND_LOOKBACK = 3
SLOPE_LOOKBACK = 5

# Stable ids + labels for the seven votes, in engine order. Matching needles
# reconstruct votes from older rows that only stored passing rationale strings.
VOTE_SPECS: tuple[tuple[str, str, str], ...] = (
    ("below_mean", "Below historical mean", "Below historical mean"),
    ("below_median", "Below historical median", "Below historical median"),
    ("within_one_stdev", "Within 1 stdev below mean", "Within 1 stdev below mean"),
    ("volume_above_mean", "Volume above average", "Volume above average"),
    ("recent_uptrend", "3-bar uptrend", "uptrend"),
    ("positive_slope", "Positive 5-bar slope", "-bar slope"),
    ("positive_sentiment", "Positive news sentiment", "Positive news sentiment"),
)


@dataclass(frozen=True, slots=True)
class Vote:
    """One of the seven deterministic checks.

    ``detail`` is the human evidence string. For a passing vote it is exactly
    the rationale phrase persisted historically; for a failing vote it explains
    why the check did not contribute. Pass/fail logic is unchanged.
    """

    id: str
    label: str
    passed: bool
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "label": self.label, "passed": self.passed, "detail": self.detail}


@dataclass(frozen=True, slots=True)
class RecommendationResult:
    ticker: str
    score: int
    recommend: bool
    rationale: list[str]
    computed_at: datetime
    votes: list[Vote]


def _vote_below_mean(current: float, mean: float) -> Vote:
    passed = current < mean
    if passed:
        detail = f"Below historical mean (${current:.2f} < ${mean:.2f})"
    else:
        detail = f"Not below historical mean (${current:.2f} ≥ ${mean:.2f})"
    return Vote("below_mean", "Below historical mean", passed, detail)


def _vote_below_median(current: float, median: float) -> Vote:
    passed = current < median
    if passed:
        detail = f"Below historical median (${current:.2f} < ${median:.2f})"
    else:
        detail = f"Not below historical median (${current:.2f} ≥ ${median:.2f})"
    return Vote("below_median", "Below historical median", passed, detail)


def _vote_within_one_stdev(current: float, mean: float, stdev: float) -> Vote:
    label = "Within 1 stdev below mean"
    if stdev <= 0:
        return Vote(
            "within_one_stdev",
            label,
            False,
            "Historical stdev is zero or undefined",
        )
    if current >= mean:
        return Vote(
            "within_one_stdev",
            label,
            False,
            f"Not below the mean (${current:.2f} ≥ ${mean:.2f})",
        )
    if abs(current - mean) > stdev:
        return Vote(
            "within_one_stdev",
            label,
            False,
            f"More than 1 stdev below mean (gap ${mean - current:.2f}, stdev ${stdev:.2f})",
        )
    return Vote(
        "within_one_stdev",
        label,
        True,
        f"Within 1 stdev below mean (gap ${mean - current:.2f}, stdev ${stdev:.2f})",
    )


def _vote_volume_above_mean(current: float, mean: float) -> Vote:
    label = "Volume above average"
    if mean <= 0:
        return Vote("volume_above_mean", label, False, "Historical average volume is unavailable")
    passed = current > mean
    if passed:
        detail = f"Volume above average ({current:,.0f} vs avg {mean:,.0f})"
    else:
        detail = f"Volume not above average ({current:,.0f} vs avg {mean:,.0f})"
    return Vote("volume_above_mean", label, passed, detail)


def _vote_recent_uptrend(closes: list[float]) -> Vote:
    label = f"{TREND_LOOKBACK}-bar uptrend"
    if len(closes) < TREND_LOOKBACK:
        return Vote(
            "recent_uptrend", label, False, f"Fewer than {TREND_LOOKBACK} historical closes"
        )
    recent = closes[-TREND_LOOKBACK:]
    passed = all(recent[i] > recent[i - 1] for i in range(1, len(recent)))
    if passed:
        detail = f"{TREND_LOOKBACK}-bar uptrend ({recent[0]:.2f} → {recent[-1]:.2f})"
    else:
        detail = f"No {TREND_LOOKBACK}-bar uptrend ({recent[0]:.2f} → {recent[-1]:.2f})"
    return Vote("recent_uptrend", label, passed, detail)


def _vote_positive_sentiment(mean_score: float | None, article_count: int) -> Vote:
    """Vote when the trailing-week news sentiment is clearly positive.

    The seventh vote, and the only one that isn't derived from price. A
    symbol with no scored news simply doesn't get the vote, rather than
    being penalised for it.
    """
    label = "Positive news sentiment"
    if mean_score is None or article_count == 0:
        return Vote("positive_sentiment", label, False, "No scored headlines in the trailing week")
    if mean_score <= SENTIMENT_VOTE_THRESHOLD:
        return Vote(
            "positive_sentiment",
            label,
            False,
            f"News sentiment not clearly positive ({mean_score:+.2f} over {article_count} article(s))",
        )
    return Vote(
        "positive_sentiment",
        label,
        True,
        f"Positive news sentiment ({mean_score:+.2f} over {article_count} article(s))",
    )


def _vote_positive_slope(closes: list[float]) -> Vote:
    label = f"Positive {SLOPE_LOOKBACK}-bar slope"
    if len(closes) < SLOPE_LOOKBACK:
        return Vote(
            "positive_slope",
            label,
            False,
            f"Fewer than {SLOPE_LOOKBACK} historical closes",
        )
    y = np.array(closes[-SLOPE_LOOKBACK:], dtype=float)
    x = np.arange(SLOPE_LOOKBACK, dtype=float)
    try:
        slope = float(np.polyfit(x, y, 1)[0])
    except (np.linalg.LinAlgError, ValueError):
        return Vote("positive_slope", label, False, "Slope could not be estimated")
    passed = slope > 0
    if passed:
        detail = f"Positive {SLOPE_LOOKBACK}-bar slope ({slope:+.4f}/bar)"
    else:
        detail = f"Non-positive {SLOPE_LOOKBACK}-bar slope ({slope:+.4f}/bar)"
    return Vote("positive_slope", label, passed, detail)


def votes_from_rationale(rationale: list[str]) -> list[Vote]:
    """Rebuild the seven-vote list from stored passing rationale strings.

    Older recommendation rows only persisted the passing phrases. Failed
    votes are marked as not contributing; their metric detail is unknown.
    """
    remaining = list(rationale)
    votes: list[Vote] = []
    for vote_id, label, needle in VOTE_SPECS:
        match = next((item for item in remaining if needle.lower() in item.lower()), None)
        if match is not None:
            remaining.remove(match)
            votes.append(Vote(vote_id, label, True, match))
        else:
            votes.append(
                Vote(
                    vote_id,
                    label,
                    False,
                    f"{label} did not contribute to this score",
                )
            )
    return votes


def votes_from_payload(payload: list[Any] | None, rationale: list[str]) -> list[Vote]:
    """Prefer persisted structured votes; fall back to rationale reconstruction."""
    if not payload:
        return votes_from_rationale(rationale)
    votes: list[Vote] = []
    for item in payload:
        if not isinstance(item, dict):
            return votes_from_rationale(rationale)
        try:
            votes.append(
                Vote(
                    id=str(item["id"]),
                    label=str(item["label"]),
                    passed=bool(item["passed"]),
                    detail=str(item["detail"]),
                )
            )
        except KeyError:
            return votes_from_rationale(rationale)
    if len(votes) != MAX_SCORE:
        return votes_from_rationale(rationale)
    return votes


def score_ticker(
    ticker: str,
    bars: list[tuple[Decimal, int]],
    *,
    sentiment_7d: float | None = None,
    sentiment_article_count: int = 0,
) -> RecommendationResult | None:
    """Compute the recommendation for one ticker.

    ``bars`` is an ordered list of ``(close, volume)`` tuples, oldest first.
    Returns ``None`` if there isn't enough data to score; the caller should
    skip writing a row in that case rather than persist a zero score.

    ``sentiment_7d`` is the trailing-week mean news sentiment from
    ``symbol_metrics``. Omit it (the default) and the score behaves exactly as
    the original six-vote algo did.
    """

    if len(bars) < MIN_DATA_POINTS:
        return None

    closes = [float(b[0]) for b in bars]
    volumes = [float(b[1]) for b in bars]

    current_price = closes[-1]
    current_volume = volumes[-1]
    hist_prices = closes[:-1]
    hist_volumes = volumes[:-1]

    hist_mean = float(np.mean(hist_prices))
    hist_median = float(np.median(hist_prices))
    hist_stdev = float(np.std(hist_prices, ddof=1)) if len(hist_prices) > 1 else 0.0
    hist_vol_mean = float(np.mean(hist_volumes))

    votes = [
        _vote_below_mean(current_price, hist_mean),
        _vote_below_median(current_price, hist_median),
        _vote_within_one_stdev(current_price, hist_mean, hist_stdev),
        _vote_volume_above_mean(current_volume, hist_vol_mean),
        _vote_recent_uptrend(hist_prices),
        _vote_positive_slope(hist_prices),
        _vote_positive_sentiment(sentiment_7d, sentiment_article_count),
    ]
    rationale = [vote.detail for vote in votes if vote.passed]
    score = len(rationale)
    return RecommendationResult(
        ticker=ticker,
        score=score,
        recommend=score >= VOTE_THRESHOLD,
        rationale=rationale,
        computed_at=utcnow(),
        votes=votes,
    )


def _load_recent_bars(
    session: Session, ticker: str, *, lookback: int = 30
) -> list[tuple[Decimal, int]]:
    stmt = (
        select(PriceBar)
        .where(PriceBar.ticker == ticker, PriceBar.interval == "1d")
        .order_by(PriceBar.ts.desc())  # type: ignore[attr-defined]
        .limit(lookback)
    )
    rows = list(session.exec(stmt).all())
    rows.reverse()
    return [(r.close, r.volume) for r in rows]


def score_universe(
    session: Session,
    *,
    lookback: int = 30,
    persist: bool = True,
) -> list[RecommendationResult]:
    """Run the algo against every active symbol; optionally persist.

    Returns the list of computed results. When ``persist=True`` we also
    write one row per ticker into ``recommendations`` so the API can serve
    them directly. The CLI uses this for one-off runs; the scheduler does
    too, daily.
    """

    tickers = list(session.exec(select(Symbol.ticker).where(Symbol.is_active)).all())

    # One lookup for the whole universe's sentiment, rather than per ticker.
    sentiment_by_ticker = {
        row.ticker: (row.sentiment_7d, row.sentiment_article_count)
        for row in session.exec(select(SymbolMetrics)).all()
    }

    results: list[RecommendationResult] = []
    for ticker in tickers:
        bars = _load_recent_bars(session, ticker, lookback=lookback)
        mean_score, article_count = sentiment_by_ticker.get(ticker, (None, 0))
        result = score_ticker(
            ticker,
            bars,
            sentiment_7d=mean_score,
            sentiment_article_count=article_count,
        )
        if result is None:
            logger.info("recommend: %s skipped — insufficient bars (%d)", ticker, len(bars))
            continue
        results.append(result)
        if persist:
            session.add(
                Recommendation(
                    ticker=result.ticker,
                    score=Decimal(result.score),
                    rationale="; ".join(result.rationale) or None,
                    votes=[vote.as_dict() for vote in result.votes],
                    computed_at=result.computed_at,
                )
            )
    if persist:
        session.commit()
    return results
