"""Explicit versioned lookup for execution profiles.

Callers must not construct ad-hoc ``ExecutionProfile`` objects for live paper
trading. Unknown name/version pairs fail; there is no silent fallback to
``legacy_close``. Future names (ideal, retail_realistic, …) are reserved in
docs and are **not** registered until their economics exist.
"""

from __future__ import annotations

from stockviz.services.simulation.contracts import ExecutionProfile
from stockviz.services.simulation.profiles import (
    LEGACY_CLOSE,
    LEGACY_CLOSE_MODEL_VERSION,
    LEGACY_CLOSE_NAME,
    NEXT_OPEN,
    NEXT_OPEN_MODEL_VERSION,
    NEXT_OPEN_NAME,
)

EXECUTION_PROFILES: dict[tuple[str, str], ExecutionProfile] = {
    (LEGACY_CLOSE_NAME, LEGACY_CLOSE_MODEL_VERSION): LEGACY_CLOSE,
    # Phase 5.3: backtests only. Live paper trading stays on legacy_close.
    (NEXT_OPEN_NAME, NEXT_OPEN_MODEL_VERSION): NEXT_OPEN,
}


class UnknownExecutionProfileError(LookupError):
    """Raised when ``get_execution_profile`` cannot find a registered pair."""


def get_execution_profile(name: str, version: str) -> ExecutionProfile:
    """Return the canonical profile for ``(name, version)``.

    Does not fall back to another version of the same name, and does not
    treat a lookalike dataclass as ``legacy_close``.
    """

    try:
        return EXECUTION_PROFILES[(name, version)]
    except KeyError as exc:
        raise UnknownExecutionProfileError(
            f"Unknown execution profile {name!r} version {version!r}"
        ) from exc


LIVE_PAPER_EXECUTION_PROFILE = get_execution_profile(LEGACY_CLOSE_NAME, LEGACY_CLOSE_MODEL_VERSION)
"""Fixed live-paper profile. Not user-selectable. Equal to ``LEGACY_CLOSE``."""
