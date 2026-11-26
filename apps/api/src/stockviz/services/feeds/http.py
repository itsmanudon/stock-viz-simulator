"""The one HTTP edge of the feed adapters (A6.3).

``HttpGet`` is ``(url, params, headers) -> httpx.Response``; tests pass a
function that answers from the hand-written fixtures, so no test reaches a
provider. :func:`get_json` takes a rate-limit token, sends the request,
retries a 429 (at most ``RATE_RETRIES`` times, waiting its Retry-After) and
turns everything else into a classified :class:`FeedError` whose text is
fixed: never the URL's query, a header or the provider's body.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from decimal import Decimal
from typing import Any

import httpx

from stockviz.services.feeds.base import (
    FeedNetworkError,
    FeedProviderError,
    FeedRateError,
    classify_status,
)
from stockviz.services.feeds.ratelimit import RateLimiter

HttpGet = Callable[[str, dict[str, str], dict[str, str]], httpx.Response]

RATE_RETRIES = 2
DEFAULT_RETRY_AFTER = 60.0
TIMEOUT_SECONDS = 30.0


def default_get(url: str, params: dict[str, str], headers: dict[str, str]) -> httpx.Response:
    return httpx.get(url, params=params, headers=headers, timeout=TIMEOUT_SECONDS)


def _retry_after(response: httpx.Response) -> float | None:
    raw = response.headers.get("Retry-After", "").strip()
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if value >= 0 else None


def get_json(
    provider: str,
    url: str,
    *,
    params: dict[str, str],
    headers: dict[str, str],
    limiter: RateLimiter,
    get: HttpGet = default_get,
) -> Any:
    """GET ``url`` and decode its JSON (numbers as ``Decimal``), classified on failure."""
    for attempt in range(RATE_RETRIES + 1):
        limiter.acquire()
        try:
            response = get(url, params, headers)
        except httpx.TimeoutException:
            raise FeedNetworkError(provider, "request timed out") from None
        except httpx.RequestError:
            # The exception's text holds the request URL; never pass it on.
            raise FeedNetworkError(provider, "could not reach the provider") from None
        if response.status_code == 429 and attempt < RATE_RETRIES:
            limiter.pause(_retry_after(response) or DEFAULT_RETRY_AFTER)
            continue
        if response.status_code != 200:
            raise classify_status(provider, response.status_code, _retry_after(response))
        try:
            return json.loads(response.content, parse_float=Decimal, parse_int=Decimal)
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise FeedProviderError(provider, "answered without valid JSON") from None
    raise FeedRateError(provider, "rate limit reached")  # pragma: no cover - loop returns
