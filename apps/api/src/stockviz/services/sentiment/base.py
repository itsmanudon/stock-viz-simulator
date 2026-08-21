"""The sentiment provider contract.

Sentiment used to be a single function that called Anthropic directly from the
news ingest path, returning one categorical label. That was fine as a feature
(a badge on a headline) and wrong as a pipeline: there was no way to swap the
model, compare two models, or connect a separate scoring service.

Everything downstream now depends on :class:`SentimentProvider`. Implementations
live alongside this module:

- ``anthropic_provider.AnthropicProvider`` — Claude Haiku, the original path.
- ``http_provider.HttpProvider``           — POSTs to a standalone scoring
  service. This is the seam a separate sentiment-analysis repository plugs
  into; see ``docs/SENTIMENT.md`` for the wire contract.
- ``null_provider.NullProvider``           — scores nothing. The default, so
  dev and CI need no key and no network.

Selection happens in ``get_provider()``, driven by ``SENTIMENT_PROVIDER``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

Label = Literal["positive", "neutral", "negative"]

VALID_LABELS: frozenset[str] = frozenset({"positive", "neutral", "negative"})


@dataclass(frozen=True, slots=True)
class SentimentScore:
    """One scored document.

    ``score`` is the signal downstream code aggregates: a continuous value in
    [-1, 1] where -1 is maximally negative. ``label`` is the categorical view
    of the same judgement, kept because the UI badge reads it directly.

    ``confidence`` is optional — the Anthropic classifier doesn't report one,
    but most local models do, and storing it lets a caller drop low-confidence
    scores out of an aggregate.

    ``model`` identifies what produced this, which is what makes re-scoring and
    A/B comparison possible. A bare label column could express none of this.
    """

    label: Label
    score: float
    model: str
    confidence: float | None = None

    def __post_init__(self) -> None:
        if self.label not in VALID_LABELS:
            raise ValueError(f"invalid sentiment label: {self.label!r}")
        if not -1.0 <= self.score <= 1.0:
            raise ValueError(f"score must be in [-1, 1], got {self.score}")
        if self.confidence is not None and not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence must be in [0, 1], got {self.confidence}")


@dataclass(frozen=True, slots=True)
class SentimentInput:
    """A document to score.

    ``headline`` alone is what the original implementation sent. ``summary`` is
    fetched by the news ingest and was being discarded; most sentiment models
    do measurably better on headline plus lede, so providers receive both and
    decide what to use.
    """

    headline: str
    summary: str | None = None
    ticker: str | None = None

    def as_text(self) -> str:
        """Headline plus lede, which is what a provider scores by default."""
        if not self.summary:
            return self.headline
        return f"{self.headline}\n\n{self.summary}"


@runtime_checkable
class SentimentProvider(Protocol):
    """Scores documents. One call may cover many inputs."""

    name: str

    def score(self, inputs: list[SentimentInput]) -> list[SentimentScore | None]:
        """Return one result per input, in order.

        ``None`` means "not scored" — a transient failure, a filtered input, or
        a disabled provider. Callers persist NULL rather than guessing, so a
        later backfill can retry exactly those rows. Implementations must never
        raise for an individual document; a failed batch degrades to all-None.
        """
        ...


def label_from_score(score: float, *, neutral_band: float = 0.15) -> Label:
    """Bucket a continuous score into a label.

    Providers that return only a number use this so the categorical column
    stays consistent across models instead of each one inventing a threshold.
    """
    if score > neutral_band:
        return "positive"
    if score < -neutral_band:
        return "negative"
    return "neutral"


def score_from_label(label: Label) -> float:
    """Nominal numeric value for a provider that returns only a label.

    Deliberately +/-1 and 0 rather than something softer: a classifier that
    reports no confidence is asserting the category outright, and pretending
    otherwise would understate it in an average.
    """
    return {"positive": 1.0, "neutral": 0.0, "negative": -1.0}[label]
