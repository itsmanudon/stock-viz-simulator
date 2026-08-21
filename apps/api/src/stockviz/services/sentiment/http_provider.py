"""Sentiment from a standalone scoring service.

This is the integration point for a separate sentiment-analysis repository.
Running the model as its own service (rather than importing it as a library)
keeps its dependencies — torch, transformers, a CUDA runtime — out of the API
image, which matters a lot on Render's free tier, and lets the two deploy on
their own cadences.

The wire contract is small and versioned; ``docs/SENTIMENT.md`` is the
authority. In brief:

    POST {SENTIMENT_SERVICE_URL}/score
    Content-Type: application/json
    Authorization: Bearer {SENTIMENT_SERVICE_TOKEN}   (optional)

    {"documents": [{"text": "...", "ticker": "AAPL"}, ...]}

    200 OK
    {
      "model": "finbert-v2",
      "results": [
        {"label": "positive", "score": 0.82, "confidence": 0.91},
        null,
        ...
      ]
    }

``results`` must be the same length as ``documents`` and in the same order.
A ``null`` entry means "this one could not be scored" and is persisted as NULL
so a later backfill can retry it.
"""

from __future__ import annotations

import logging

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from stockviz.services.sentiment.base import (
    VALID_LABELS,
    SentimentInput,
    SentimentScore,
    label_from_score,
)

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_BATCH_SIZE = 50


class HttpProvider:
    """POSTs batches to an external scoring service."""

    def __init__(
        self,
        *,
        base_url: str,
        token: str = "",
        model_hint: str = "external",
        batch_size: int = DEFAULT_BATCH_SIZE,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        client: httpx.Client | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._batch_size = batch_size
        self._timeout = timeout
        # Injectable so tests exercise the parsing without a live service.
        self._client = client
        self.name = model_hint

    def score(self, inputs: list[SentimentInput]) -> list[SentimentScore | None]:
        if not inputs:
            return []
        if not self._base_url:
            logger.warning("sentiment: SENTIMENT_SERVICE_URL not set; skipping")
            return [None] * len(inputs)

        out: list[SentimentScore | None] = []
        for i in range(0, len(inputs), self._batch_size):
            out.extend(self._score_batch(inputs[i : i + self._batch_size]))
        return out

    @retry(
        retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    def _post(self, payload: dict) -> dict:
        headers = {"Content-Type": "application/json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"

        if self._client is not None:
            response = self._client.post(
                f"{self._base_url}/score", json=payload, headers=headers, timeout=self._timeout
            )
        else:
            response = httpx.post(
                f"{self._base_url}/score", json=payload, headers=headers, timeout=self._timeout
            )
        response.raise_for_status()
        return response.json()

    def _score_batch(self, batch: list[SentimentInput]) -> list[SentimentScore | None]:
        payload = {"documents": [{"text": item.as_text(), "ticker": item.ticker} for item in batch]}
        try:
            body = self._post(payload)
        except Exception:
            logger.exception("sentiment: scoring service call failed for %d items", len(batch))
            return [None] * len(batch)

        model = str(body.get("model") or self.name)
        results = body.get("results")
        if not isinstance(results, list) or len(results) != len(batch):
            logger.error(
                "sentiment: service returned %s results for %d documents",
                len(results) if isinstance(results, list) else type(results).__name__,
                len(batch),
            )
            return [None] * len(batch)

        return [_parse_result(item, model) for item in results]


def _parse_result(item: object, model: str) -> SentimentScore | None:
    """Turn one service result into a SentimentScore, or None if unusable.

    Tolerant on purpose: the service is a separate codebase that may evolve
    ahead of this one. A result missing ``label`` is derived from ``score``;
    a malformed entry is dropped rather than failing its whole batch.
    """
    if item is None or not isinstance(item, dict):
        return None

    raw_score = item.get("score")
    if not isinstance(raw_score, (int, float)):
        return None
    score = max(-1.0, min(1.0, float(raw_score)))

    label = item.get("label")
    if not isinstance(label, str) or label not in VALID_LABELS:
        label = label_from_score(score)

    confidence = item.get("confidence")
    if not isinstance(confidence, (int, float)):
        confidence = None
    else:
        confidence = max(0.0, min(1.0, float(confidence)))

    try:
        return SentimentScore(
            label=label,  # type: ignore[arg-type]
            score=score,
            model=str(item.get("model") or model),
            confidence=confidence,
        )
    except ValueError:
        logger.warning("sentiment: rejected malformed result %r", item)
        return None
