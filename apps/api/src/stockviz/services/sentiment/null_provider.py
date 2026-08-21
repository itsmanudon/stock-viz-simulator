"""A provider that scores nothing.

The default. Dev, CI, and any deployment without a configured model get this,
so news ingest runs unchanged with no key and no network access. Returning
None (rather than a neutral score) is deliberate: NULL means "not scored yet"
and the backfill CLI can find those rows later, whereas a stored 0.0 would be
indistinguishable from a genuine neutral judgement.
"""

from __future__ import annotations

from stockviz.services.sentiment.base import SentimentInput, SentimentScore


class NullProvider:
    name = "none"

    def score(self, inputs: list[SentimentInput]) -> list[SentimentScore | None]:
        return [None] * len(inputs)
