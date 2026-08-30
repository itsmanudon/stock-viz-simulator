"""Plausibility screening for ingested price bars (F-011).

Nothing else validates provider data before it reaches ``price_bars``, and a
negative, zero, or absurd close flows straight into fills, alerts, NAV,
backtests, and replay. ``Numeric(18, 6)`` only rejects non-numerics.

Two classes of check:

* **Structural** — invariants a real OHLC bar never violates (non-positive or
  non-finite prices, ``low <= open, close <= high``, negative volume). A bar
  failing these is corrupt and carries no recoverable information, so it is
  **rejected**: dropped with a ``WARNING``.
* **Plausibility** — the bar is internally consistent but suspicious relative
  to context (an enormous intrabar range, or a day-over-day move far past
  anything organic). Real markets *do* produce these (halt-resumes, biotech
  binary events, bank runs), so dropping them would lose real data. They are
  **quarantined**: stored in ``price_bar_quarantine`` for review, not in
  ``price_bars``.

This module is pure — no DB, no network. The writer in
:mod:`stockviz.services.ingest.prices` supplies the prior close and routes
each verdict.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from stockviz.services.ingest.prices import BarRecord

# --- tunable thresholds ----------------------------------------------------
#
# 60% sits above essentially every organic single-day equity move while
# still catching a whole-row decimal-point error (~900%). It interacts with
# the *unadjusted* price series: a stock split of 3:1 or more shows up as a
# ~67%+ "move" and will be quarantined. That is acceptable — nothing else in
# the repo detects splits, and a human glance at a split date is desirable.

MAX_INTRABAR_RANGE_RATIO = Decimal("0.60")
"""Reject-free ceiling on ``(high - low) / low`` before a bar is quarantined."""

MAX_ABS_DAILY_RETURN = Decimal("0.60")
"""Ceiling on ``|close - prev_close| / prev_close`` before a bar is quarantined."""

MAX_CONSECUTIVE_DAY_OVER_DAY_QUARANTINE = 2
"""How many consecutive day-over-day quarantines the batch walker tolerates
before it re-anchors the trusted prior close to the current level.

A transient bad print spikes for a day or two and then the series snaps back —
that snap-back looks like a second big move, so parking those follow-on days is
correct. But a *sustained* run means the price level genuinely shifted (a split
in an unadjusted history, a currency redenomination, a v1-CSV series seam), and
without a re-anchor every remaining bar in the batch would quarantine against a
now-stale close. Re-anchoring quarantines the discontinuity itself and the days
it takes to confirm, not the decade of real history behind it."""


class Disposition(StrEnum):
    ACCEPT = "accept"
    QUARANTINE = "quarantine"
    REJECT = "reject"


@dataclass(frozen=True, slots=True)
class Verdict:
    disposition: Disposition
    reason: str = ""


_ACCEPT = Verdict(Disposition.ACCEPT)

_PRICE_FIELDS = ("open", "high", "low", "close")


def screen_bar(bar: BarRecord, prev_close: Decimal | None = None) -> Verdict:
    """Classify one bar. ``prev_close`` is the trusted close of the prior bar,
    or ``None`` when no prior close is known (the day-over-day check is then
    skipped)."""

    # --- structural: reject ------------------------------------------------
    for name in _PRICE_FIELDS:
        value: Decimal = getattr(bar, name)
        if value is None or not value.is_finite():
            return Verdict(Disposition.REJECT, f"{name} is not a finite number ({value!r})")
        if value <= 0:
            return Verdict(Disposition.REJECT, f"{name} must be positive (got {value})")

    if not bar.volume.is_finite() or bar.volume < 0:
        return Verdict(
            Disposition.REJECT, f"volume must be finite and non-negative (got {bar.volume})"
        )

    if not (bar.low <= bar.open <= bar.high and bar.low <= bar.close <= bar.high):
        return Verdict(
            Disposition.REJECT,
            f"OHLC out of order: low={bar.low} open={bar.open} high={bar.high} close={bar.close}",
        )

    # --- plausibility: quarantine ---------------------------------------------
    intrabar_range = (bar.high - bar.low) / bar.low
    if intrabar_range > MAX_INTRABAR_RANGE_RATIO:
        return Verdict(
            Disposition.QUARANTINE,
            f"intrabar range {intrabar_range:.1%} exceeds {MAX_INTRABAR_RANGE_RATIO:.0%}",
        )

    if prev_close is not None and prev_close > 0:
        move = abs(bar.close - prev_close) / prev_close
        if move > MAX_ABS_DAILY_RETURN:
            return Verdict(
                Disposition.QUARANTINE,
                f"close moved {move:.1%} from prior close {prev_close}, "
                f"exceeds {MAX_ABS_DAILY_RETURN:.0%}",
            )

    return _ACCEPT
