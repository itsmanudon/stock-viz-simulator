"""The shared shape of the HTTP history adapters (A6.3)."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

from stockviz.services.feeds.base import (
    Capabilities,
    FeedBar,
    FeedNotConfigured,
    NotSupported,
    Tick,
)
from stockviz.services.feeds.http import HttpGet, default_get
from stockviz.services.feeds.ratelimit import Clock, RateLimiter, Sleep

STREAM_LATER = "streaming is built in A6.5 (worker) and A6.6 (live feed)"


def wall_clock() -> datetime:
    return datetime.now(UTC)


@dataclass
class HttpFeed:
    """Base for adapters: key check, rate limiter, injectable HTTP, clocks.

    ``now`` is the wall clock (Alpaca's SIP rule); ``clock`` and ``sleep``
    drive the rate limiter. Subclasses set ``name``, ``label`` and
    ``capabilities`` and implement ``minute_bars``.
    """

    key: str = ""
    get: HttpGet = default_get
    clock: Clock = time.monotonic
    sleep: Sleep = time.sleep
    now: Callable[[], datetime] = wall_clock
    limiter: RateLimiter = field(init=False)

    name = "base"
    label = "Base"
    capabilities = Capabilities(history=False, stream=False, coverage=())

    def __post_init__(self) -> None:
        self.limiter = RateLimiter.from_specs(
            self.capabilities.rate_limits, clock=self.clock, sleep=self.sleep
        )

    @property
    def configured(self) -> bool:
        return bool(self.key.strip())

    def _require_key(self) -> str:
        if not self.configured:
            raise FeedNotConfigured(f"{self.label} is not configured on this server")
        return self.key.strip()

    def minute_bars(self, symbol: str, start: datetime, end: datetime) -> list[FeedBar]:
        raise NotSupported(self.label, "history is not built for this provider")

    def stream(self, symbols: Sequence[str]) -> AsyncIterator[Tick | FeedBar]:
        raise NotSupported(self.label, STREAM_LATER)

    def __repr__(self) -> str:  # never print the key
        return f"{type(self).__name__}(configured={self.configured})"
