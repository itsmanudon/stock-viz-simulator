"""Recommendation engine.

Ported from the v1 ``scripts/algo.py`` 6-vote system, then extended with a
7th vote from trailing news sentiment. Adapted to read ``PriceBar`` rows
from Postgres instead of CSVs. Each vote captures one common-sense signal:

  1. Current close < historical mean (potential buy-low)
  2. Current close < historical median
  3. Current close within one stdev below the mean (not extreme)
  4. Current volume > historical mean (increased interest)
  5. Last 3 historical closes strictly increasing (short-term uptrend)
  6. Positive slope over the last 5 historical closes (linear momentum)
  7. Trailing-week mean news sentiment clearly positive (optional; skipped
     when no scored headlines exist — not a penalty)

Score >= 4 reads as a buy. We expose both the score and the per-vote
rationale so the UI can show *why* a ticker scored where it did.
"""

from stockviz.services.recommend.engine import (
    MAX_SCORE,
    MIN_DATA_POINTS,
    VOTE_THRESHOLD,
    RecommendationResult,
    score_ticker,
    score_universe,
)

__all__ = [
    "MAX_SCORE",
    "MIN_DATA_POINTS",
    "VOTE_THRESHOLD",
    "RecommendationResult",
    "score_ticker",
    "score_universe",
]
