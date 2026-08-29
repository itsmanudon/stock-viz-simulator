"""Monotonic simulation instant.

The kernel still does not read a clock. Callers that need "current time"
construct a ``SimulationClock`` with an explicit instant and pass that instant
into ``OrderIntent.submitted_at`` / ``MarketSnapshot.observed_at``.

This type never reads the wall clock.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime


class SimulationClockError(ValueError):
    """Invalid simulation-clock construction or advance."""


def _aware_utc(value: datetime, *, field: str) -> datetime:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise SimulationClockError(f"{field} must be timezone-aware")
    return value.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class SimulationClock:
    """A single simulation 'now'. Time only moves forward."""

    now: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "now", _aware_utc(self.now, field="now"))

    def instant(self) -> datetime:
        return self.now

    def permits(self, observed_at: datetime) -> bool:
        """True when ``observed_at`` is knowable at this clock (not in its future)."""

        observed = _aware_utc(observed_at, field="observed_at")
        return observed <= self.now

    def advance_to(self, instant: datetime) -> SimulationClock:
        """Return a clock at ``instant``. Refuses to move backwards."""

        instant = _aware_utc(instant, field="instant")
        if instant < self.now:
            raise SimulationClockError(
                "simulation clock cannot move backwards "
                f"({instant.isoformat()} < {self.now.isoformat()})"
            )
        if instant == self.now:
            return self
        return replace(self, now=instant)
