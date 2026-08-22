"""7-vote recommendation engine over ``PriceBar`` rows.

Pure function ``score_ticker(bars)`` takes the bar series and returns a
``RecommendationResult`` with the integer score (0..MAX_SCORE), the boolean
``recommend`` flag, and per-vote rationale strings. ``score_universe``
iterates every active symbol in the DB and writes the latest result into
the ``recommendations`` table so the API can serve it without re-running
the algo per request.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

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


@dataclass(frozen=True, slots=True)
class RecommendationResult:
    ticker: str
    score: int
    recommend: bool
    rationale: list[str]
    computed_at: datetime


def _vote_below_mean(current: float, mean: float) -> str | None:
    return f"Below historical mean (${current:.2f} < ${mean:.2f})" if current < mean else None


def _vote_below_median(current: float, median: float) -> str | None:
    return f"Below historical median (${current:.2f} < ${median:.2f})" if current < median else None


def _vote_within_one_stdev(current: float, mean: float, stdev: float) -> str | None:
    if stdev <= 0 or current >= mean:
        return None
    if abs(current - mean) > stdev:
        return None
    return f"Within 1 stdev below mean (gap ${mean - current:.2f}, stdev ${stdev:.2f})"


def _vote_volume_above_mean(current: float, mean: float) -> str | None:
    if mean <= 0:
        return None
    return f"Volume above average ({current:,.0f} vs avg {mean:,.0f})" if current > mean else None


def _vote_recent_uptrend(closes: list[float]) -> str | None:
    if len(closes) < TREND_LOOKBACK:
        return None
    recent = closes[-TREND_LOOKBACK:]
    if all(recent[i] > recent[i - 1] for i in range(1, len(recent))):
        return f"{TREND_LOOKBACK}-bar uptrend ({recent[0]:.2f} → {recent[-1]:.2f})"
    return None


def _vote_positive_sentiment(mean_score: float | None, article_count: int) -> str | None:
    """Vote when the trailing-week news sentiment is clearly positive.

    The seventh vote, and the only one that isn't derived from price. It gives
    ``/recommendations`` a reason to move when the news does — previously the
    sentiment pipeline fed a badge and nothing else.
    """
    if mean_score is None or article_count == 0:
        return None
    if mean_score <= SENTIMENT_VOTE_THRESHOLD:
        return None
    return f"Positive news sentiment ({mean_score:+.2f} over {article_count} article(s))"


def _vote_positive_slope(closes: list[float]) -> str | None:
    if len(closes) < SLOPE_LOOKBACK:
        return None
    y = np.array(closes[-SLOPE_LOOKBACK:], dtype=float)
    x = np.arange(SLOPE_LOOKBACK, dtype=float)
    try:
        slope = float(np.polyfit(x, y, 1)[0])
    except (np.linalg.LinAlgError, ValueError):
        return None
    return f"Positive {SLOPE_LOOKBACK}-bar slope ({slope:+.4f}/bar)" if slope > 0 else None


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

    rationale: list[str] = []
    for vote in (
        _vote_below_mean(current_price, hist_mean),
        _vote_below_median(current_price, hist_median),
        _vote_within_one_stdev(current_price, hist_mean, hist_stdev),
        _vote_volume_above_mean(current_volume, hist_vol_mean),
        _vote_recent_uptrend(hist_prices),
        _vote_positive_slope(hist_prices),
        _vote_positive_sentiment(sentiment_7d, sentiment_article_count),
    ):
        if vote is not None:
            rationale.append(vote)

    score = len(rationale)
    return RecommendationResult(
        ticker=ticker,
        score=score,
        recommend=score >= VOTE_THRESHOLD,
        rationale=rationale,
        computed_at=utcnow(),
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
                    computed_at=result.computed_at,
                )
            )
    if persist:
        session.commit()
    return results
