"""The first read-only presets (A2.2, design note section 5 "Presets").

System setups (``user_id`` null, ``is_preset``) that a user can load into the
screener or fork. Each uses only data StockViz holds today (daily bars, the
venue index, point-in-time fundamentals), and each description states where
its formula comes from and where it falls short. Every rule is also in the
conformance corpus (``tests/test_dsl_conformance.py``).

``seed_presets`` runs inside ``stockviz.cli seed`` and is idempotent: a preset
is found by ``preset_key``; its name and description follow the code, and a
changed rule becomes a new version (versions are immutable), so a saved
screen or alert that names an old version keeps its exact rule.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlmodel import Session, col, select

from stockviz.models.setup import Setup
from stockviz.services.dsl import compile_rule
from stockviz.services.setups.store import UserScopedRule, add_version


@dataclass(frozen=True)
class Preset:
    key: str
    name: str
    kind: str
    description: str
    rule: str


MINERVINI = Preset(
    key="minervini-trend-template",
    name="Minervini trend template",
    kind="screen",
    description=(
        "Source: Mark Minervini, Trade Like a Stock Market Wizard (2013), the "
        "eight-point trend template. Covered: (1) close above the 150- and "
        "200-day averages; (2) the 150-day above the 200-day; (3) the 200-day "
        "rising for at least a month (above its value 21 sessions ago); (4) the "
        "50-day above the 150- and 200-day; (5) close above the 50-day; (6) close "
        "at least 30% above the 52-week low; (7) close within 25% of the "
        "52-week high. Approximated: (8) Minervini asks for an IBD-style relative "
        "strength rating of 70 or more, a percentile against all stocks; StockViz "
        "has no such rating, so this uses rs(252) > 0: the 12-month return beat "
        "the venue's index (^GSPC or ^NSEI). The 52-week range uses daily highs "
        "and lows of the last 252 sessions."
    ),
    rule=(
        "close > sma(close, 150) and close > sma(close, 200)\n"
        "and sma(close, 150) > sma(close, 200)\n"
        "and sma(close, 200) > sma(close, 200)[21]\n"
        "and sma(close, 50) > sma(close, 150) and sma(close, 50) > sma(close, 200)\n"
        "and close > sma(close, 50)\n"
        "and close >= 1.3 * lowest(low, 252)\n"
        "and close >= 0.75 * highest(high, 252)\n"
        "and rs(252) > 0"
    ),
)

BREAKOUT = Preset(
    key="52-week-high-breakout-volume",
    name="52-week-high breakout on rising volume",
    kind="screen",
    description=(
        "Source: the new-high breakout common to Nicolas Darvas (How I Made "
        "$2,000,000 in the Stock Market, 1960) and William O'Neil (How to Make "
        "Money in Stocks), which both want volume well above normal on the "
        "breakout. Formula: today's close is above the highest high of the "
        "previous 252 sessions, today's volume is at least 1.5 times its 50-day "
        "average, and the 10-day average volume is above the 50-day (volume "
        "rising into the move). Limits: daily bars only, so an intraday breakout "
        "that closed back below the high does not count; the 1.5x threshold is a "
        "convention, not from either book."
    ),
    rule=(
        "close > highest(high, 252)[1]\n"
        "and volume >= 1.5 * sma(volume, 50)\n"
        "and sma(volume, 10) > sma(volume, 50)"
    ),
)

RSI_PULLBACK = Preset(
    key="rsi-pullback-uptrend",
    name="RSI pullback in an uptrend",
    kind="screen",
    description=(
        "Source: Larry Connors and Cesar Alvarez, Short Term Trading Strategies "
        "That Work (2008): buy short-term weakness only in a long-term uptrend, "
        "with the 2-period RSI under 10 while the close is above the 200-day "
        "average. Added here: the 50-day above the 200-day, so the uptrend is "
        "more than one bar above the average. Limits: the book also gives exit "
        "rules (close above the 5-day average); a screen only finds the entry "
        "condition, and nothing here is a recommendation."
    ),
    rule=("close > sma(close, 200)\nand sma(close, 50) > sma(close, 200)\nand rsi(2) < 10"),
)

PIOTROSKI = Preset(
    key="piotroski-style-quality",
    name="Piotroski-style quality screen",
    kind="screen",
    description=(
        "Source: Joseph Piotroski, 'Value Investing: The Use of Historical "
        "Financial Statement Information to Separate Winners from Losers' "
        "(Journal of Accounting Research, 2000), the nine-point F-score. "
        "StockViz's fundamentals (fundamental.*) are levels as known on each "
        "date, with no year-over-year history in a rule yet, so only part of "
        "the score fits. Covered: F1, return on assets above zero. Approximated: "
        "F2 (operating cash flow above zero) by a positive price-to-free-cash-"
        "flow, which needs free cash flow above zero, a stricter test; a company "
        "with negative free cash flow shows as unknown, not as failing. Replaced "
        "by levels: F5 (leverage fell) by debt to equity under 1, and F6 "
        "(current ratio rose) by a current ratio above 1. Not covered: F3 (ROA "
        "rose), F4 (cash flow above net income), F7 (no new shares), F8 (gross "
        "margin rose), F9 (asset turnover rose). Fundamentals are yfinance's, "
        "dated by when StockViz fetched them, so they are not point in time "
        "before collection began."
    ),
    rule=(
        "fundamental.roa > 0\n"
        "and fundamental.p_fcf > 0\n"
        "and fundamental.debt_to_equity < 1\n"
        "and fundamental.current_ratio > 1"
    ),
)

PRESETS: tuple[Preset, ...] = (MINERVINI, BREAKOUT, RSI_PULLBACK, PIOTROSKI)


def seed_presets(session: Session) -> dict[str, str]:
    """Create or update every screen preset. Returns key -> "created" | "new
    version" | "unchanged". The A2.4 checklist dimensions are system setups
    too, seeded by ``services/checklist/dimensions.py::seed_dimensions``."""
    return seed_setups(session, PRESETS)


def seed_setups(session: Session, presets: tuple[Preset, ...]) -> dict[str, str]:
    """Create or update the given system setups, idempotently (see the module
    docstring). Returns key -> "created" | "new version" | "unchanged"."""
    report: dict[str, str] = {}
    for preset in presets:
        rule = compile_rule(preset.rule)
        if rule.user_scoped:
            raise UserScopedRule(f"preset {preset.key} reads drawings; presets cannot")
        setup = session.exec(select(Setup).where(col(Setup.preset_key) == preset.key)).first()
        status = "unchanged"
        if setup is None:
            setup = Setup(
                user_id=None,
                name=preset.name,
                kind=preset.kind,
                description=preset.description,
                is_preset=True,
                preset_key=preset.key,
            )
            session.add(setup)
            session.flush()
            status = "created"
        elif (setup.name, setup.description, setup.kind) != (
            preset.name,
            preset.description,
            preset.kind,
        ):
            setup.name, setup.description, setup.kind = (
                preset.name,
                preset.description,
                preset.kind,
            )
            session.add(setup)
        saved = add_version(session, setup, rule, commit=False)
        if saved.created and status == "unchanged":
            status = "new version"
        report[preset.key] = status
    session.commit()
    return report


__all__ = ["PRESETS", "Preset", "seed_presets", "seed_setups"]
