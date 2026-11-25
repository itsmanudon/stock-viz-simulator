"""The universe stamp on every backtest result (A1.4a, part of M1.5).

Workspace ``docs/a1-design-note.md`` section 5. Every backtest today runs on
the pinned seed list (``seed-data/companies.json``) with provider history:
names that were delisted or dropped out are not in it, so results carry
survivorship bias. A1.4b (point-in-time universes) changes this one function,
and ``screen_universe`` (A2.2, the screener's stamp) with it.
"""

from __future__ import annotations

from typing import Any

from stockviz.schemas import UniverseOut

PINNED_UNIVERSE = "pinned"

PINNED_NOTE = (
    "Run on the pinned symbol list with today's provider history. Companies "
    "that were delisted or dropped out are missing, so results can look "
    "better than they would have at the time (survivorship bias)."
)


def universe_for(ticker: str) -> UniverseOut:
    """The universe ``ticker``'s backtest ran on. Every symbol is pinned today."""
    del ticker  # A1.4b: look up the symbol's point-in-time membership here.
    return UniverseOut(
        name=PINNED_UNIVERSE,
        point_in_time=False,
        survivorship_biased=True,
        note=PINNED_NOTE,
    )


SCREEN_NOTE = (
    "Screened on the pinned symbol list with today's provider history. "
    "Companies that were delisted or dropped out are missing, so a screen "
    "dated in the past shows only today's survivors (survivorship bias)."
)


def screen_universe() -> UniverseOut:
    """The universe a screener page ran on (A2.2). Pinned today, like backtests."""
    return UniverseOut(
        name=PINNED_UNIVERSE,
        point_in_time=False,
        survivorship_biased=True,
        note=SCREEN_NOTE,
    )


EVIDENCE_NOTE = (
    "Graded on the pinned symbol list with today's provider history. "
    "Companies that were delisted or dropped out are missing, so the study "
    "sees only today's survivors and a grade can look better than it would "
    "have at the time (survivorship bias)."
)


def evidence_universe() -> UniverseOut:
    """The universe a checklist evidence grade was measured on (A2.4). Pinned
    today, like backtests and screens; A1.4b changes it."""
    return UniverseOut(
        name=PINNED_UNIVERSE,
        point_in_time=False,
        survivorship_biased=True,
        note=EVIDENCE_NOTE,
    )


def universe_json(ticker: str) -> dict[str, Any]:
    """:func:`universe_for` as stored in an experiment run's JSON result."""
    return universe_for(ticker).model_dump(mode="json")


__all__ = [
    "EVIDENCE_NOTE",
    "PINNED_NOTE",
    "PINNED_UNIVERSE",
    "SCREEN_NOTE",
    "evidence_universe",
    "screen_universe",
    "universe_for",
    "universe_json",
]
