"""Versioned fee schedules (Phase 5.3).

Pure. A schedule turns one fill (side, quantity, price) into named fee
components in the instrument's currency. Rates are published figures, fixed
in code under a version; a rate change is a new version, never an edit, so a
stored run keeps the schedule it used.

``us_equity_2026`` (sources checked 12 Nov 2026):

- SEC Section 31 fee on sales: $20.60 per million of sale value, the FY2026
  rate in force from 4 Apr 2026 (SEC Fee Rate Advisory 2026-2).
- FINRA Trading Activity Fee on sales: $0.000195 per share, at most $9.79 a
  trade (FINRA Section 1 schedule, 2026 step). FINRA filed SR-FINRA-2026-021
  to pause it for Oct-Dec 2026; not modelled.
- Commission: the run's ``commission_bps`` (0 by default), charged both ways.

The same rates apply to every date in a run: a backtest over 2015 uses 2026
rates. The result says which schedule it used.

``none``: commission only.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from stockviz.services.simulation.contracts import OrderSide

CENTS = Decimal("0.01")
MICROS = Decimal("0.000001")
BPS = Decimal(10_000)


@dataclass(frozen=True)
class FeeBreakdown:
    components: tuple[tuple[str, Decimal], ...]

    @property
    def total(self) -> Decimal:
        return sum((amount for _name, amount in self.components), Decimal(0))


@dataclass(frozen=True)
class FeeSchedule:
    name: str
    version: str
    sec_rate_per_million: Decimal = Decimal(0)
    taf_per_share: Decimal = Decimal(0)
    taf_max_per_trade: Decimal = Decimal(0)

    def fees(
        self,
        side: OrderSide,
        quantity: Decimal,
        price: Decimal,
        *,
        commission_bps: Decimal = Decimal(0),
    ) -> FeeBreakdown:
        notional = price * quantity
        parts: list[tuple[str, Decimal]] = []
        if commission_bps:
            parts.append(("commission", (notional * commission_bps / BPS).quantize(MICROS)))
        if side is OrderSide.SELL:
            if self.sec_rate_per_million:
                sec = (notional * self.sec_rate_per_million / Decimal(1_000_000)).quantize(
                    CENTS, rounding=ROUND_HALF_UP
                )
                parts.append(("sec_section_31", sec))
            if self.taf_per_share:
                taf = min(quantity * self.taf_per_share, self.taf_max_per_trade).quantize(
                    CENTS, rounding=ROUND_HALF_UP
                )
                parts.append(("finra_taf", taf))
        return FeeBreakdown(tuple((n, a) for n, a in parts if a))


NONE = FeeSchedule(name="none", version="v1")
US_EQUITY_2026 = FeeSchedule(
    name="us_equity_2026",
    version="v1",
    sec_rate_per_million=Decimal("20.60"),
    taf_per_share=Decimal("0.000195"),
    taf_max_per_trade=Decimal("9.79"),
)

FEE_SCHEDULES: dict[str, FeeSchedule] = {s.name: s for s in (NONE, US_EQUITY_2026)}


class UnknownFeeScheduleError(LookupError):
    pass


def get_fee_schedule(name: str) -> FeeSchedule:
    try:
        return FEE_SCHEDULES[name]
    except KeyError as exc:
        raise UnknownFeeScheduleError(f"Unknown fee schedule {name!r}") from exc
