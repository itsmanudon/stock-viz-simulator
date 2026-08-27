"""Versioned execution profiles.

SIM-01 implements ``LEGACY_CLOSE`` only. Names such as ideal / retail /
conservative / stress / custom are documented in ``docs/SIMULATION.md`` and
must not be treated as implemented here.
"""

from __future__ import annotations

from stockviz.services.simulation.contracts import ExecutionProfile

LEGACY_CLOSE_NAME = "legacy_close"
LEGACY_CLOSE_MODEL_VERSION = "v1"

LEGACY_CLOSE_ASSUMPTIONS: tuple[str, ...] = (
    "Uses stored 1d close",
    "No spread model",
    "No slippage model",
    "No partial fill model",
    "Does not use same-day OHLC high/low touches",
)

LEGACY_CLOSE = ExecutionProfile(
    name=LEGACY_CLOSE_NAME,
    model_version=LEGACY_CLOSE_MODEL_VERSION,
    assumptions=LEGACY_CLOSE_ASSUMPTIONS,
)


def is_legacy_close(profile: ExecutionProfile) -> bool:
    return profile.name == LEGACY_CLOSE_NAME and profile.model_version == LEGACY_CLOSE_MODEL_VERSION
