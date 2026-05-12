"""News-headline sentiment classification via the Anthropic API.

Returns ``"positive" | "neutral" | "negative" | None`` per input headline.
Designed to be a no-op when ``ANTHROPIC_API_KEY`` is unset so dev/CI runs
don't need the key. The Anthropic client is constructed per call (rare path,
short-lived) — we don't keep a global to avoid pulling the SDK at import time
when the feature is disabled.

Model: ``claude-haiku-4-5-20251001`` — cheapest/fastest tier for short
classification work. Inputs are batched to keep the per-call overhead amortized.
"""

from __future__ import annotations

import json
import logging
from typing import Literal

try:  # pragma: no cover - exercised at runtime in production
    from anthropic import Anthropic
except ImportError:  # pragma: no cover - dev/CI fallback when anthropic is absent
    Anthropic = None  # type: ignore[assignment, misc]

logger = logging.getLogger(__name__)

Sentiment = Literal["positive", "neutral", "negative"]

DEFAULT_BATCH_SIZE = 20

SYSTEM_PROMPT = (
    "You are a financial-news sentiment classifier. For each headline, decide "
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


def _classify_batch(client, headlines: list[str]) -> list[Sentiment | None]:
    """One Anthropic call for up to DEFAULT_BATCH_SIZE headlines.

    On any failure we degrade to all-None for this batch — the caller treats
    None as "not classified yet" and writes NULL to the DB.
    """

    if not headlines:
        return []

    numbered = "\n".join(f"{i + 1}. {h}" for i, h in enumerate(headlines))
    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            system=SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Classify these {len(headlines)} headlines. Respond with a JSON "
                        f'object {{"sentiments": [...]}} whose array has exactly '
                        f"{len(headlines)} entries in the same order as the headlines.\n\n"
                        f"{numbered}"
                    ),
                }
            ],
            output_config={
                "format": {"type": "json_schema", "schema": _result_schema(len(headlines))}
            },
        )
    except Exception:
        logger.exception("sentiment: Anthropic API call failed for %d headlines", len(headlines))
        return [None] * len(headlines)

    # Extract the text content from the assistant's first text block.
    raw_text = ""
    for block in response.content:
        if getattr(block, "type", None) == "text":
            raw_text = block.text
            break

    try:
        parsed = json.loads(raw_text)
        items = parsed.get("sentiments")
        if not isinstance(items, list) or len(items) != len(headlines):
            raise ValueError(f"unexpected shape: {parsed!r}")
        out: list[Sentiment | None] = []
        for item in items:
            if item in ("positive", "neutral", "negative"):
                out.append(item)  # type: ignore[arg-type]
            else:
                out.append(None)
        return out
    except (json.JSONDecodeError, ValueError, AttributeError):
        logger.exception("sentiment: could not parse response: %r", raw_text)
        return [None] * len(headlines)


def score_headlines(
    headlines: list[str],
    *,
    api_key: str,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> list[Sentiment | None]:
    """Classify a list of headlines. Returns one sentiment (or None) per input.

    Returns all-None if ``api_key`` is empty so callers can run unconditionally
    without an env-var check at every site.
    """

    if not headlines:
        return []
    if not api_key:
        return [None] * len(headlines)
    if Anthropic is None:
        logger.warning("sentiment: 'anthropic' package not installed; skipping")
        return [None] * len(headlines)

    client = Anthropic(api_key=api_key)
    out: list[Sentiment | None] = []
    for i in range(0, len(headlines), batch_size):
        out.extend(_classify_batch(client, headlines[i : i + batch_size]))
    return out
