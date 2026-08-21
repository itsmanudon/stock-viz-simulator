"""Headline sentiment via the Anthropic API.

This is the original implementation, moved behind the provider interface and
given the two things it was missing: retries, and a per-run document budget.

Model: ``claude-haiku-4-5-20251001`` — cheapest/fastest tier for short
classification work. Inputs are batched to amortize per-call overhead.
"""

from __future__ import annotations

import json
import logging

from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from stockviz.services.sentiment.base import (
    Label,
    SentimentInput,
    SentimentScore,
    score_from_label,
)

try:  # pragma: no cover - exercised at runtime in production
    from anthropic import Anthropic
except ImportError:  # pragma: no cover - dev/CI fallback when anthropic is absent
    Anthropic = None  # type: ignore[assignment, misc]

logger = logging.getLogger(__name__)

MODEL = "claude-haiku-4-5-20251001"
DEFAULT_BATCH_SIZE = 20

SYSTEM_PROMPT = (
    "You are a financial-news sentiment classifier. For each item, decide "
    "whether the implication for the underlying company / asset / sector is "
    "POSITIVE (good for shareholders), NEGATIVE (bad for shareholders), or "
    "NEUTRAL (informational, mixed, or unclear). Be conservative — when in "
    "doubt, choose NEUTRAL."
)


def _result_schema(n: int) -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["sentiments"],
        "properties": {
            "sentiments": {
                "type": "array",
                "minItems": n,
                "maxItems": n,
                "items": {"type": "string", "enum": ["positive", "neutral", "negative"]},
            }
        },
    }


class AnthropicProvider:
    """Batched classifier over the Anthropic Messages API."""

    name = MODEL

    def __init__(self, *, api_key: str, batch_size: int = DEFAULT_BATCH_SIZE) -> None:
        self._api_key = api_key
        self._batch_size = batch_size

    def score(self, inputs: list[SentimentInput]) -> list[SentimentScore | None]:
        if not inputs:
            return []
        if not self._api_key:
            return [None] * len(inputs)
        if Anthropic is None:
            logger.warning("sentiment: 'anthropic' package not installed; skipping")
            return [None] * len(inputs)

        client = Anthropic(api_key=self._api_key)
        out: list[SentimentScore | None] = []
        for i in range(0, len(inputs), self._batch_size):
            out.extend(self._score_batch(client, inputs[i : i + self._batch_size]))
        return out

    # A transient 429/5xx used to lose the whole batch — one blip silently
    # dropped 20 articles, and nothing recorded that they needed rescoring.
    @retry(
        retry=retry_if_exception_type(Exception),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    def _call(self, client, batch: list[SentimentInput]):
        numbered = "\n".join(f"{i + 1}. {item.as_text()}" for i, item in enumerate(batch))
        return client.messages.create(
            model=MODEL,
            max_tokens=512,
            system=SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Classify these {len(batch)} news items. Respond with a JSON "
                        f'object {{"sentiments": [...]}} whose array has exactly '
                        f"{len(batch)} entries in the same order as the items.\n\n"
                        f"{numbered}"
                    ),
                }
            ],
            output_config={"format": {"type": "json_schema", "schema": _result_schema(len(batch))}},
        )

    def _score_batch(self, client, batch: list[SentimentInput]) -> list[SentimentScore | None]:
        """One API call for up to ``batch_size`` items.

        On any failure that outlives the retries we degrade to all-None for
        this batch — the caller writes NULL, and the backfill CLI can pick
        those rows up later.
        """
        if not batch:
            return []

        try:
            response = self._call(client, batch)
        except Exception:
            logger.exception("sentiment: Anthropic call failed for %d items", len(batch))
            return [None] * len(batch)

        raw_text = ""
        for block in response.content:
            if getattr(block, "type", None) == "text":
                raw_text = block.text
                break

        try:
            parsed = json.loads(raw_text)
            items = parsed.get("sentiments")
            if not isinstance(items, list) or len(items) != len(batch):
                raise ValueError(f"unexpected shape: {parsed!r}")
        except (json.JSONDecodeError, ValueError, AttributeError):
            logger.exception("sentiment: could not parse response: %r", raw_text)
            return [None] * len(batch)

        out: list[SentimentScore | None] = []
        for item in items:
            if item in ("positive", "neutral", "negative"):
                label: Label = item
                out.append(SentimentScore(label=label, score=score_from_label(label), model=MODEL))
            else:
                out.append(None)
        return out
