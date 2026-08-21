"""Sentiment scoring: provider selection and the public surface.

``get_provider()`` is the only thing callers need. Selection is driven by
``SENTIMENT_PROVIDER``:

- ``none``      (default) — score nothing, so dev/CI need no key and no network
- ``anthropic``           — Claude Haiku, using ``ANTHROPIC_API_KEY``
- ``http``                — a standalone scoring service at
                            ``SENTIMENT_SERVICE_URL`` (see docs/SENTIMENT.md)

``anthropic`` also stays the implicit default when ``ANTHROPIC_API_KEY`` is set
and no provider is named, so existing deployments keep working untouched.
"""

from __future__ import annotations

import logging

from stockviz.services.sentiment.base import (
    Label,
    SentimentInput,
    SentimentProvider,
    SentimentScore,
    label_from_score,
    score_from_label,
)
from stockviz.services.sentiment.null_provider import NullProvider
from stockviz.settings import Settings, get_settings

logger = logging.getLogger(__name__)

__all__ = [
    "Label",
    "NullProvider",
    "SentimentInput",
    "SentimentProvider",
    "SentimentScore",
    "get_provider",
    "label_from_score",
    "score_from_label",
]


def get_provider(settings: Settings | None = None) -> SentimentProvider:
    """Build the configured provider. Never raises — falls back to NullProvider."""
    settings = settings or get_settings()
    choice = (settings.sentiment_provider or "").strip().lower()

    if not choice:
        # Back-compat: a deployment that only ever set ANTHROPIC_API_KEY keeps
        # the behaviour it had before providers existed.
        choice = "anthropic" if settings.anthropic_api_key else "none"

    if choice == "none":
        return NullProvider()

    if choice == "anthropic":
        if not settings.anthropic_api_key:
            logger.warning(
                "sentiment: provider 'anthropic' selected but ANTHROPIC_API_KEY is empty"
            )
            return NullProvider()
        from stockviz.services.sentiment.anthropic_provider import AnthropicProvider

        return AnthropicProvider(api_key=settings.anthropic_api_key)

    if choice == "http":
        if not settings.sentiment_service_url:
            logger.warning("sentiment: provider 'http' selected but SENTIMENT_SERVICE_URL is empty")
            return NullProvider()
        from stockviz.services.sentiment.http_provider import HttpProvider

        return HttpProvider(
            base_url=settings.sentiment_service_url,
            token=settings.sentiment_service_token,
            model_hint=settings.sentiment_model_hint or "external",
        )

    logger.warning("sentiment: unknown SENTIMENT_PROVIDER %r; scoring disabled", choice)
    return NullProvider()
