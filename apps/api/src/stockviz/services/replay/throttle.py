"""A per-user limit on replay advances (A6.9, M9.4 autoplay).

Autoplay drives the clock by calling ``advance`` from the browser at up to 10
bars a second. The page's calls reach the API through the web server, which
the slowapi limiter exempts (``limiter.py``, audit RS-6), so the limit is kept
here, keyed on the authenticated user: at most :data:`ADVANCE_LIMIT` advances
in any :data:`ADVANCE_WINDOW_SECONDS` window, for replay sessions and drills
together. A refused call changes nothing and is told when to retry (HTTP 429
with ``Retry-After``).

The window lives in the API process. Several API replicas would each keep
their own; a single process is what runs today.
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from collections.abc import Callable

ADVANCE_LIMIT = 15
"""Advances per window: autoplay's fastest speed (10 a second) plus headroom
for a manual step or a retried call."""
ADVANCE_WINDOW_SECONDS = 1.0


class AdvanceThrottle:
    def __init__(
        self,
        limit: int = ADVANCE_LIMIT,
        window: float = ADVANCE_WINDOW_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.limit = limit
        self.window = window
        self.clock = clock
        self._calls: dict[int, deque[float]] = {}
        self._lock = threading.Lock()

    def check(self, user_id: int) -> float | None:
        """None when the advance may go ahead (and it is counted), else the
        seconds to wait before the next one is allowed."""
        now = self.clock()
        with self._lock:
            calls = self._calls.setdefault(user_id, deque())
            while calls and now - calls[0] >= self.window:
                calls.popleft()
            if len(calls) >= self.limit:
                return max(0.0, self.window - (now - calls[0]))
            calls.append(now)
            return None

    def reset(self) -> None:
        with self._lock:
            self._calls.clear()


ADVANCE_THROTTLE = AdvanceThrottle()


def retry_after_header(wait: float) -> str:
    """``Retry-After`` in whole seconds (at least 1)."""
    return str(max(1, math.ceil(wait)))


__all__ = [
    "ADVANCE_LIMIT",
    "ADVANCE_THROTTLE",
    "ADVANCE_WINDOW_SECONDS",
    "AdvanceThrottle",
    "retry_after_header",
]
