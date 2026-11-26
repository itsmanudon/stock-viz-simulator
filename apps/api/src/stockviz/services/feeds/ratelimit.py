"""Client-side rate limiting from each provider's documented limits (A6.3).

A :class:`RateLimiter` holds one token bucket per documented limit (Tiingo's
free plan has an hourly and a daily one). ``acquire()`` waits until every
bucket has a token, then takes one from each. The clock and the sleep are
injected, so tests run on a fake clock and never wait.

``estimate_seconds(calls)`` is the shortest time ``calls`` requests can take
from full buckets: the backfill's dry-run plan prints it.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from stockviz.services.feeds.base import RateLimitSpec

Clock = Callable[[], float]
Sleep = Callable[[float], None]


@dataclass
class TokenBucket:
    capacity: float
    per_second: float
    clock: Clock
    tokens: float = field(init=False)
    updated: float = field(init=False)

    def __post_init__(self) -> None:
        if self.capacity <= 0 or self.per_second <= 0:
            raise ValueError("a token bucket needs a positive capacity and rate")
        self.tokens = self.capacity
        self.updated = self.clock()

    def _refill(self) -> None:
        now = self.clock()
        self.tokens = min(self.capacity, self.tokens + (now - self.updated) * self.per_second)
        self.updated = now

    def wait_time(self) -> float:
        """Seconds until one token is available (0 when one is)."""
        self._refill()
        return 0.0 if self.tokens >= 1 else (1 - self.tokens) / self.per_second

    def take(self) -> None:
        self._refill()
        self.tokens -= 1


@dataclass
class RateLimiter:
    buckets: Sequence[TokenBucket]
    sleep: Sleep = time.sleep
    waited: float = 0.0
    """Total seconds spent waiting (reported by the backfill)."""

    @classmethod
    def from_specs(
        cls,
        specs: Sequence[RateLimitSpec],
        *,
        clock: Clock = time.monotonic,
        sleep: Sleep = time.sleep,
    ) -> RateLimiter:
        return cls(
            buckets=[TokenBucket(s.calls, s.calls / s.per_seconds, clock) for s in specs],
            sleep=sleep,
        )

    def acquire(self) -> None:
        while True:
            wait = max((b.wait_time() for b in self.buckets), default=0.0)
            if wait <= 0:
                break
            self.waited += wait
            self.sleep(wait)
        for bucket in self.buckets:
            bucket.take()

    def pause(self, seconds: float) -> None:
        """Wait out a provider's Retry-After (a 429) before the next call."""
        if seconds > 0:
            self.waited += seconds
            self.sleep(seconds)


def estimate_seconds(specs: Sequence[RateLimitSpec], calls: int) -> float:
    """Least time for ``calls`` requests starting from full buckets."""
    if calls <= 0:
        return 0.0
    return max(
        (max(0.0, (calls - s.calls) * s.per_seconds / s.calls) for s in specs),
        default=0.0,
    )
