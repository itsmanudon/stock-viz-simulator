"""The six checklist dimensions (A2.4, M4.4), written in the Rule DSL.

The Checklist replaces the 7-vote Signals. Each dimension is a short list of
named conditions with a published, well-known formula. A dimension is
**met** when every condition is met, **unknown** when an input is missing and
no condition failed, else **not met** (Kleene's ``and``: exactly what the DSL
gives the conjunction of the conditions, see :func:`aggregate`).

Each dimension is stored as a system setup of kind ``checklist`` (``user_id``
null, ``is_preset``, ``preset_key`` ``checklist-<key>``), through the A2.2
preset mechanism: its rule is the ``and`` of its conditions, so it is
versioned, hashed and visible in ``/v1/setups/presets`` like any preset, and a
changed formula becomes a new version (scores and evidence name the version
they used).

**Scopes.** Delivery (the share of traded shares taken into demat) is an
NSE/BSE figure; no US exchange publishes it. So Volume/Delivery has two
setups: ``india`` (NSE and BSE listings: volume and delivery) and ``other``
(volume only). Every other dimension has one setup for every listing. Until
A1's NSE files are loaded the delivery condition is unknown, so an Indian
listing's Volume/Delivery is unknown, never "not met".

Wording is neutral on purpose ("4 of 6 met"). Nothing here is a
recommendation to buy or sell, and the page says so (SEBI research-analyst
rules).
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlmodel import Session, col, select

from stockviz.models.setup import Setup, SetupVersion
from stockviz.services.dsl import CompiledRule, compile_rule
from stockviz.services.markets.calendar import venue_for_ticker
from stockviz.services.setups.presets import Preset, seed_setups

KIND = "checklist"
INDIA_VENUES = frozenset({"XNSE", "XBOM"})
SCOPE_ALL = "all"
SCOPE_INDIA = "india"
SCOPE_OTHER = "other"


@dataclass(frozen=True)
class Condition:
    label: str
    rule: str
    scopes: frozenset[str] | None = None
    """None: every listing. Else only listings in these scopes."""


@dataclass(frozen=True)
class Dimension:
    key: str
    name: str
    summary: str
    source: str
    conditions: tuple[Condition, ...]
    scopes: tuple[str, ...] = (SCOPE_ALL,)

    def conditions_for(self, scope: str) -> tuple[Condition, ...]:
        return tuple(c for c in self.conditions if c.scopes is None or scope in c.scopes)

    def preset_key(self, scope: str) -> str:
        return f"checklist-{self.key}" if scope == SCOPE_ALL else f"checklist-{self.key}-{scope}"

    def rule_for(self, scope: str) -> str:
        return "\nand ".join(f"({c.rule})" for c in self.conditions_for(scope))


TREND = Dimension(
    key="trend",
    name="Trend",
    summary="The close is above its 200-day average, and the 50-day average is above the 200-day.",
    source=(
        "The long-term trend filter of trend-following practice: price above "
        "the 200-day moving average, and the 50-day above the 200-day (a "
        "'golden cross' state). Both are points of Mark Minervini's trend "
        "template (Trade Like a Stock Market Wizard, 2013)."
    ),
    conditions=(
        Condition("Close above the 200-day average", "close > sma(close, 200)"),
        Condition("50-day average above the 200-day", "sma(close, 50) > sma(close, 200)"),
    ),
)

MOMENTUM = Dimension(
    key="momentum",
    name="Momentum / relative strength",
    summary=("The 6-month return beat the venue's index, and the 14-day RSI is between 50 and 70."),
    source=(
        "Relative strength: the 6-month (126-session) return against the "
        "venue's index (^GSPC or ^NSEI), after Jegadeesh and Titman, 'Returns "
        "to Buying Winners and Selling Losers' (Journal of Finance, 1993), "
        "whose momentum effect is strongest at 3 to 12 months. RSI: J. Welles "
        "Wilder, New Concepts in Technical Trading Systems (1978); 50 to 70 is "
        "the bull-range convention of Andrew Cardwell and Constance Brown "
        "(strength without being overbought above 70)."
    ),
    conditions=(
        Condition("6-month return above the index's", "rs(126) > 0"),
        Condition("RSI(14) at least 50", "rsi(14) >= 50"),
        Condition("RSI(14) at most 70", "rsi(14) <= 70"),
    ),
)

VOLUME = Dimension(
    key="volume",
    name="Volume / delivery",
    summary=(
        "Today's volume is above its 50-day average; on NSE and BSE listings, "
        "more than half of the traded shares were taken for delivery."
    ),
    source=(
        "Volume above its 50-day average is the participation test William "
        "O'Neil uses (How to Make Money in Stocks). Delivery percentage is "
        "published by NSE and BSE in the security-wise delivery file; above "
        "50% is a common Indian-market reading that most shares traded were "
        "taken into demat accounts rather than squared off intraday. US exchanges publish no delivery figure, so "
        "US listings are judged on volume alone. Until NSE files are loaded "
        "(A1) the delivery condition is unknown."
    ),
    conditions=(
        Condition("Volume above its 50-day average", "volume > sma(volume, 50)"),
        Condition(
            "Delivery above 50% of traded shares",
            "delivery_pct > 50",
            scopes=frozenset({SCOPE_INDIA}),
        ),
    ),
    scopes=(SCOPE_INDIA, SCOPE_OTHER),
)

REGIME = Dimension(
    key="regime",
    name="Market regime",
    summary="The venue's index (^GSPC or ^NSEI) closed above its own 200-day average.",
    source=(
        "The market-regime filter: the broad index above its 200-day moving "
        "average, as in Mebane Faber, 'A Quantitative Approach to Tactical "
        "Asset Allocation' (Journal of Wealth Management, 2007), which uses "
        "the 10-month average, of which the 200-day is the daily form. The "
        "index close is the stored ^GSPC or ^NSEI bar on the stock's date "
        "(forward-filled at most 5 bars), so the average runs over the "
        "stock's sessions."
    ),
    conditions=(
        Condition("Index above its 200-day average", "index_close > sma(index_close, 200)"),
    ),
)

QUALITY = Dimension(
    key="quality",
    name="Quality",
    summary="Return on equity above 15%, and debt below equity.",
    source=(
        "Two common quality thresholds: return on equity above 15% (Warren "
        "Buffett's Berkshire Hathaway letters cite 15% as a mark of a good "
        "business; it is the usual screen cut-off) and debt to equity under 1 "
        "(as in Benjamin Graham's defensive-investor balance-sheet tests, The "
        "Intelligent Investor, 1949). Fundamentals are yfinance's (and SEC "
        "EDGAR's where set), as known on each date: they are point in time "
        "only from when StockViz began collecting them, so older dates are "
        "unknown."
    ),
    conditions=(
        Condition("Return on equity above 15%", "fundamental.roe > 15"),
        Condition("Debt to equity below 1", "fundamental.debt_to_equity < 1"),
    ),
)

RISK = Dimension(
    key="risk",
    name="Risk / reward",
    summary=(
        "The close is within 25% of its 52-week high, and the 14-day average "
        "true range is under 4% of the close."
    ),
    source=(
        "Within 25% of the 52-week high is a point of Minervini's trend "
        "template (stocks near their highs, not deep in a drawdown). Average "
        "true range: Wilder (1978); under 4% of the close bounds the daily "
        "swing, so a stop one ATR away is a small share of the position. The "
        "4% bound is a convention, not from either source. The 52-week high "
        "is the highest daily high of the last 252 sessions."
    ),
    conditions=(
        Condition("Within 25% of the 52-week high", "close >= 0.75 * highest(high, 252)"),
        Condition("ATR(14) under 4% of the close", "atr(14) < 0.04 * close"),
    ),
)

DIMENSIONS: tuple[Dimension, ...] = (TREND, MOMENTUM, VOLUME, REGIME, QUALITY, RISK)
DIMENSION_BY_KEY = {d.key: d for d in DIMENSIONS}


def scope_for(ticker: str, dimension: Dimension) -> str:
    """Which of ``dimension``'s setups judges ``ticker``."""
    if dimension.scopes == (SCOPE_ALL,):
        return SCOPE_ALL
    return SCOPE_INDIA if venue_for_ticker(ticker) in INDIA_VENUES else SCOPE_OTHER


def in_scope(ticker: str, dimension: Dimension, scope: str) -> bool:
    return scope == SCOPE_ALL or scope_for(ticker, dimension) == scope


def _description(dimension: Dimension, scope: str) -> str:
    where = {
        SCOPE_ALL: "",
        SCOPE_INDIA: " This setup judges NSE and BSE listings.",
        SCOPE_OTHER: " This setup judges listings outside India (no delivery data).",
    }[scope]
    return f"Checklist dimension: {dimension.summary}{where} Source: {dimension.source}"


def _name(dimension: Dimension, scope: str) -> str:
    suffix = {SCOPE_ALL: "", SCOPE_INDIA: " (India)", SCOPE_OTHER: " (outside India)"}[scope]
    return f"Checklist: {dimension.name}{suffix}"


CHECKLIST_PRESETS: tuple[Preset, ...] = tuple(
    Preset(
        key=d.preset_key(scope),
        name=_name(d, scope),
        kind=KIND,
        description=_description(d, scope),
        rule=d.rule_for(scope),
    )
    for d in DIMENSIONS
    for scope in d.scopes
)


@dataclass(frozen=True)
class Variant:
    """One dimension setup, compiled, with the version that holds its rule."""

    dimension: Dimension
    scope: str
    setup: Setup
    version: SetupVersion
    rule: CompiledRule
    conditions: tuple[tuple[Condition, CompiledRule], ...]


def seed_dimensions(session: Session) -> dict[str, str]:
    """Create or update the checklist setups (idempotent). The nightly
    ``checklist`` and weekly ``checklist-evidence`` jobs call this, since the
    cron never runs ``seed``."""
    return seed_setups(session, CHECKLIST_PRESETS)


def load_variants(session: Session, *, seed: bool = True) -> dict[tuple[str, str], Variant]:
    """(dimension key, scope) -> its setup and the version holding today's rule.

    The version is found by the rule's hash, not as the newest: a formula
    changed back returns its older version."""
    if seed:
        seed_dimensions(session)
    out: dict[tuple[str, str], Variant] = {}
    for d in DIMENSIONS:
        for scope in d.scopes:
            rule = compile_rule(d.rule_for(scope))
            setup = session.exec(
                select(Setup).where(col(Setup.preset_key) == d.preset_key(scope))
            ).first()
            if setup is None or setup.id is None:
                raise LookupError(f"checklist setup {d.preset_key(scope)} is not seeded")
            version = session.exec(
                select(SetupVersion).where(
                    SetupVersion.setup_id == setup.id, SetupVersion.rule_hash == rule.hash
                )
            ).first()
            if version is None:
                raise LookupError(f"checklist setup {d.preset_key(scope)} lacks its current rule")
            conditions = tuple((c, compile_rule(c.rule)) for c in d.conditions_for(scope))
            out[(d.key, scope)] = Variant(d, scope, setup, version, rule, conditions)
    return out


def aggregate(statuses: list[str]) -> str:
    """Kleene's ``and`` over condition results: any not met -> not met, else
    any unknown -> unknown, else met. An empty list is met (vacuous)."""
    if "not_met" in statuses:
        return "not_met"
    if "unknown" in statuses:
        return "unknown"
    return "met"


__all__ = [
    "CHECKLIST_PRESETS",
    "DIMENSIONS",
    "DIMENSION_BY_KEY",
    "INDIA_VENUES",
    "KIND",
    "SCOPE_ALL",
    "SCOPE_INDIA",
    "SCOPE_OTHER",
    "Condition",
    "Dimension",
    "Variant",
    "aggregate",
    "in_scope",
    "load_variants",
    "scope_for",
    "seed_dimensions",
]
