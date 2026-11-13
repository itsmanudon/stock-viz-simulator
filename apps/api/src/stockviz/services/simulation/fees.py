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

``in_delivery_nse_2026`` / ``in_delivery_bse_2026`` (Phase 5.6), Indian
equity delivery as charged by Zerodha, read from zerodha.com/charges on
12 Nov 2026 (the page gives no effective date):

- brokerage: 0 for delivery (the run's ``commission_bps`` is charged as
  brokerage if set);
- STT 0.1% on buy and sell, rounded to the rupee per trade;
- exchange transaction charge: NSE 0.00307%, BSE 0.00375%;
- SEBI fee: Rs 10 per crore (0.0001%);
- stamp duty: 0.015% on buys;
- GST: 18% of (brokerage + SEBI fee + transaction charge);
- DP charge: Rs 15.34 per scrip per sell (Rs 3.5 CDSL + Rs 9.5 Zerodha +
  Rs 2.34 GST), whatever the quantity.

Each schedule names its currency; a backtest refuses a schedule whose
currency is not the symbol's.

``none``: commission only, any currency.
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
    currency: str | None = None  # None: any currency (commission only)
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
    currency="USD",
    sec_rate_per_million=Decimal("20.60"),
    taf_per_share=Decimal("0.000195"),
    taf_max_per_trade=Decimal("9.79"),
)

RUPEE = Decimal(1)
CRORE = Decimal(10_000_000)


@dataclass(frozen=True)
class IndiaDeliverySchedule(FeeSchedule):
    """Indian equity delivery charges (Phase 5.6). See the module docstring."""

    stt_rate: Decimal = Decimal("0.001")
    exchange_rate: Decimal = Decimal(0)
    sebi_per_crore: Decimal = Decimal(10)
    stamp_buy_rate: Decimal = Decimal("0.00015")
    gst_rate: Decimal = Decimal("0.18")
    dp_per_sell: Decimal = Decimal("15.34")

    def fees(
        self,
        side: OrderSide,
        quantity: Decimal,
        price: Decimal,
        *,
        commission_bps: Decimal = Decimal(0),
    ) -> FeeBreakdown:
        notional = price * quantity

        def paise(value: Decimal) -> Decimal:
            return value.quantize(CENTS, rounding=ROUND_HALF_UP)

        brokerage = paise(notional * commission_bps / BPS)
        exchange = paise(notional * self.exchange_rate)
        sebi = paise(notional * self.sebi_per_crore / CRORE)
        parts: list[tuple[str, Decimal]] = [
            ("brokerage", brokerage),
            ("stt", (notional * self.stt_rate).quantize(RUPEE, rounding=ROUND_HALF_UP)),
            ("exchange_transaction", exchange),
            ("sebi", sebi),
            ("gst", paise((brokerage + exchange + sebi) * self.gst_rate)),
        ]
        if side is OrderSide.BUY:
            parts.append(("stamp_duty", paise(notional * self.stamp_buy_rate)))
        else:
            parts.append(("dp_charge", self.dp_per_sell))
        return FeeBreakdown(tuple((n, a) for n, a in parts if a))


IN_DELIVERY_NSE_2026 = IndiaDeliverySchedule(
    name="in_delivery_nse_2026",
    version="v1",
    currency="INR",
    exchange_rate=Decimal("0.0000307"),
)
IN_DELIVERY_BSE_2026 = IndiaDeliverySchedule(
    name="in_delivery_bse_2026",
    version="v1",
    currency="INR",
    exchange_rate=Decimal("0.0000375"),
)

FEE_SCHEDULES: dict[str, FeeSchedule] = {
    s.name: s for s in (NONE, US_EQUITY_2026, IN_DELIVERY_NSE_2026, IN_DELIVERY_BSE_2026)
}


class UnknownFeeScheduleError(LookupError):
    pass


def get_fee_schedule(name: str) -> FeeSchedule:
    try:
        return FEE_SCHEDULES[name]
    except KeyError as exc:
        raise UnknownFeeScheduleError(f"Unknown fee schedule {name!r}") from exc
