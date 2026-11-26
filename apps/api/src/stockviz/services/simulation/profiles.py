"""Versioned execution profiles.

``LEGACY_CLOSE`` (SIM-01) is live paper trading's: fills at the close, no
costs. ``NEXT_OPEN`` (Phase 5.3) is the backtest default: a market order fills
at the open of the bar it is evaluated on (the backtester passes the bar
after the signal), with the run's spread and slippage. ``INTRABAR_OHLC``
(A6.9, M9.4) is for replay and backtests, never live paper: resting orders
are judged on the bar's range with the open first. Names such as ideal /
retail / conservative / stress / custom stay reserved in
``docs/SIMULATION.md`` and are not implemented.
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
    """True only for the canonical profile, including its assumption tuple.

    Name and version alone are not enough: a caller must not get ``legacy_close``
    fills while publishing a different provenance string.
    """

    return profile == LEGACY_CLOSE


NEXT_OPEN_NAME = "next_open"
NEXT_OPEN_MODEL_VERSION = "v1"

NEXT_OPEN_ASSUMPTIONS: tuple[str, ...] = (
    "Market orders fill at the stored 1d open of the bar after the signal",
    "Spread and slippage from the run's cost model, against the trader",
    "No partial fill model",
    "Market orders only",
)

NEXT_OPEN = ExecutionProfile(
    name=NEXT_OPEN_NAME,
    model_version=NEXT_OPEN_MODEL_VERSION,
    assumptions=NEXT_OPEN_ASSUMPTIONS,
)


def is_next_open(profile: ExecutionProfile) -> bool:
    return profile == NEXT_OPEN


INTRABAR_OHLC_NAME = "intrabar_ohlc"
INTRABAR_OHLC_MODEL_VERSION = "v1"

INTRABAR_UNKNOWN_LABEL = "Order inside the bar unknown"
"""The label on a fill where a stop and a target were both inside one bar and
no stored minutes said which came first: the stop filled (worst case)."""

INTRABAR_OHLC_ASSUMPTIONS: tuple[str, ...] = (
    "Market orders fill at the observed bar's close",
    "Limit, stop and target orders are judged on the bar's open, high and low",
    "The open comes first: an order the open gaps through fills at the open",
    "A stop and a target both inside one bar: the stored minutes decide; "
    "without minutes the stop fills first (order inside the bar unknown)",
    "No spread or slippage unless the run's cost model adds them",
    "No partial fill model",
)

INTRABAR_OHLC = ExecutionProfile(
    name=INTRABAR_OHLC_NAME,
    model_version=INTRABAR_OHLC_MODEL_VERSION,
    assumptions=INTRABAR_OHLC_ASSUMPTIONS,
)


def is_intrabar_ohlc(profile: ExecutionProfile) -> bool:
    return profile == INTRABAR_OHLC
