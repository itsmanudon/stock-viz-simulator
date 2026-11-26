"""Date-versioned fee schedules (Phase 5.3, 5.6; A4.2 / M7.2).

Pure. A schedule (a *family*) turns one fill (side, quantity, price, fill
date) into named fee components in the instrument's currency. Each family is
a list of versions with ``effective_from`` / ``effective_to`` (inclusive), and
a fill uses the version in force on its fill date. Every rate names the
document it was copied from (``Source``: URL, title, the document's date and
the day it was read). Rates are copied, never guessed: a segment or period
whose figures could not be confirmed from a document read is left out (see
``docs/SIMULATION.md``, "Costs" and the workspace note
``docs/a4-cost-sources.md``).

**Before the first confirmed date.** A family's ``coverage_from`` is the first
date from which every rate is confirmed. A fill before it is priced with the
earliest version on file and the breakdown says so (``before_coverage``): it
is the old single-rate behaviour, made explicit, not an earlier rate.

**Segments** (Indian rates from the NSE circulars and Zerodha's published
charges page, read 26 Nov 2026):

- equity delivery and intraday, NSE and BSE;
- NSE equity futures and options (premium-based). The Finance Act 2026 STT
  change took effect on 1 Apr 2026 (NSE/FATAX/73524): futures 0.02% -> 0.05%,
  options 0.10% -> 0.15% of premium, both on the sell side. NSE folded IPFT
  into the transaction charge from 1 Mar 2026 (NSE/FA/73061; the all-in rate
  did not change). BSE F&O is left out: the two Zerodha pages read disagree on
  the BSE options charge and no BSE notice was read. STT on exercised options
  (on intrinsic value) is not modelled: the simulator does not exercise
  Indian options.

**Brokerage** is a named broker model chosen per run: ``zerodha`` (default:
delivery free; intraday and futures 0.03% or Rs 20 per executed order,
whichever is lower; options Rs 20 flat) or ``zero``. A run's
``commission_bps`` is charged on top as brokerage (``commission`` for US).

**Rounding** (a modelling choice, unchanged from Phase 5.6): STT to the rupee
per fill, every other Indian component to the paisa, half up; US SEC and TAF
to the cent; a US commission to the micro-unit. Calculators that round the
whole contract note (Zerodha's rounds stamp duty to the rupee) can differ by
a few paise.

**DP charge** is per scrip per day on sells: a second sell of the same scrip
on the same day passes ``dp_due=False``.

``none``: commission only, any currency.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from stockviz.services.simulation.contracts import OrderSide

CENTS = Decimal("0.01")
MICROS = Decimal("0.000001")
RUPEE = Decimal(1)
BPS = Decimal(10_000)
READ_ON = date(2026, 11, 26)

Rounding = Literal["unit", "cent", "micro"]
Side = Literal["buy", "sell", "both"]
Kind = Literal["value", "per_share", "flat", "gst"]


@dataclass(frozen=True)
class Source:
    url: str
    title: str
    date: str
    """The document's own date (ISO), or ``undated page``."""
    read_on: date = READ_ON


GST_NAMES = {
    "brokerage": "brokerage",
    "exchange_transaction": "exchange charge",
    "sebi": "SEBI fee",
    "ipft": "IPFT",
}


@dataclass(frozen=True)
class Component:
    """One fee component's rate within one version."""

    key: str
    label: str
    kind: Kind
    rate: Decimal
    """``value``: fraction of the fill's value; ``per_share``: amount per share;
    ``flat``: amount per fill; ``gst``: fraction of the listed components."""
    side: Side
    source: Source
    rounding: Rounding = "cent"
    cap: Decimal | None = None
    """Most charged per fill (FINRA TAF)."""
    gst_on: tuple[str, ...] = ()
    per_scrip_day: bool = False
    note: str = ""

    def rate_text(self) -> str:
        if self.kind == "value":
            pct = (self.rate * 100).normalize()
            return f"{pct:f}% of value"
        if self.kind == "gst":
            names = " + ".join(GST_NAMES.get(k, k) for k in self.gst_on)
            return f"{(self.rate * 100).normalize():f}% of {names}"
        if self.kind == "per_share":
            cap = f", at most {self.cap:f} a fill" if self.cap is not None else ""
            return f"{self.rate.normalize():f} per share{cap}"
        suffix = " per scrip per day" if self.per_scrip_day else " per fill"
        return f"{self.rate.normalize():f}{suffix}"


@dataclass(frozen=True)
class FeeVersion:
    effective_from: date
    effective_to: date | None
    """Last day in force (inclusive); None while current."""
    components: tuple[Component, ...]
    start_confirmed: bool = True
    """False when the documents read say when the version ended but not when it began."""
    notes: tuple[str, ...] = ()

    def covers(self, on: date) -> bool:
        return self.effective_from <= on and (self.effective_to is None or on <= self.effective_to)


@dataclass(frozen=True)
class BrokerageModel:
    """A broker's published brokerage for one segment."""

    key: str
    label: str
    kind: Literal["zero", "pct_or_flat", "flat"]
    pct: Decimal = Decimal(0)
    flat: Decimal = Decimal(0)
    source: Source | None = None

    def amount(self, notional: Decimal) -> Decimal:
        if self.kind == "zero":
            return Decimal(0)
        if self.kind == "flat":
            return self.flat
        return min(notional * self.pct, self.flat)

    def rate_text(self) -> str:
        if self.kind == "zero":
            return "free"
        if self.kind == "flat":
            return f"{self.flat.normalize():f} per executed order"
        return (
            f"{(self.pct * 100).normalize():f}% or {self.flat.normalize():f} per executed "
            "order, whichever is lower"
        )


@dataclass(frozen=True)
class FeeLine:
    key: str
    amount: Decimal
    component: Component | None
    """None for brokerage and commission (see ``FeeBreakdown.brokerage``)."""


@dataclass(frozen=True)
class FeeBreakdown:
    components: tuple[tuple[str, Decimal], ...]
    lines: tuple[FeeLine, ...] = ()
    version: FeeVersion | None = None
    before_coverage: bool = False
    brokerage: BrokerageModel | None = None

    @property
    def total(self) -> Decimal:
        return sum((amount for _name, amount in self.components), Decimal(0))


EMPTY = FeeBreakdown(())


def _round(value: Decimal, rounding: Rounding) -> Decimal:
    step = {"unit": RUPEE, "cent": CENTS, "micro": MICROS}[rounding]
    return value.quantize(step, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class FeeSchedule:
    """A versioned family. ``name`` is the canonical name; ``aliases`` are older
    names that map to it (``in_delivery_nse_2026`` and friends)."""

    name: str
    label: str = ""
    currency: str | None = None  # None: any currency (commission only)
    market: str = ""
    segment: str = ""
    venue: str | None = None
    versions: tuple[FeeVersion, ...] = ()
    brokerage_models: dict[str, BrokerageModel] = field(default_factory=dict)
    commission_label: str = "commission"
    commission_rounding: Rounding = "micro"
    aliases: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    @property
    def coverage_from(self) -> date | None:
        confirmed = [v.effective_from for v in self.versions if v.start_confirmed]
        return min(confirmed) if confirmed else None

    def version_on(self, on: date | None) -> tuple[FeeVersion | None, bool]:
        """The version in force on ``on`` (None: the newest) and whether ``on``
        falls before the confirmed coverage."""
        if not self.versions:
            return None, False
        ordered = sorted(self.versions, key=lambda v: v.effective_from)
        if on is None:
            return ordered[-1], False
        cover = self.coverage_from
        before = cover is not None and on < cover
        for version in ordered:
            if version.covers(on):
                return version, before
        if on < ordered[0].effective_from:
            return ordered[0], True
        return ordered[-1], before

    def fees(
        self,
        side: OrderSide,
        quantity: Decimal,
        price: Decimal,
        *,
        commission_bps: Decimal = Decimal(0),
        on: date | None = None,
        brokerage: str = "zerodha",
        dp_due: bool = True,
    ) -> FeeBreakdown:
        notional = price * quantity
        version, before = self.version_on(on)
        model = self.brokerage_models.get(brokerage) if self.brokerage_models else None
        amounts: dict[str, Decimal] = {}
        lines: list[FeeLine] = []
        commission = notional * commission_bps / BPS
        if model is not None:
            amounts["brokerage"] = _round(model.amount(notional) + commission, "cent")
            lines.append(FeeLine("brokerage", amounts["brokerage"], None))
        elif commission_bps:
            key = self.commission_label
            amounts[key] = _round(commission, self.commission_rounding)
            lines.append(FeeLine(key, amounts[key], None))
        for comp in version.components if version is not None else ():
            if comp.side != "both" and comp.side != side.value:
                continue
            if comp.kind == "value":
                amount = _round(notional * comp.rate, comp.rounding)
            elif comp.kind == "per_share":
                raw = quantity * comp.rate
                if comp.cap is not None:
                    raw = min(raw, comp.cap)
                amount = _round(raw, comp.rounding)
            elif comp.kind == "flat":
                if comp.per_scrip_day and not dp_due:
                    continue
                amount = comp.rate
            else:  # gst
                base = sum((amounts.get(k, Decimal(0)) for k in comp.gst_on), Decimal(0))
                amount = _round(base * comp.rate, comp.rounding)
            amounts[comp.key] = amount
            lines.append(FeeLine(comp.key, amount, comp))
        kept = tuple(line for line in lines if line.amount)
        return FeeBreakdown(
            components=tuple((line.key, line.amount) for line in kept),
            lines=kept,
            version=version,
            before_coverage=before,
            brokerage=model,
        )


# --- Sources (read 26 Nov 2026) -------------------------------------------

ZERODHA_CHARGES = Source(
    "https://zerodha.com/charges",
    "Zerodha brokerage charges, fees & taxes on trading and investing",
    "undated page",
)
NSE_STT_2026 = Source(
    "https://nsearchives.nseindia.com/content/circulars/FATAX73524.pdf",
    "NSE/FATAX/73524: Revision in rates of Securities Transaction Tax (Finance Act, 2026)",
    "2026-03-31",
)
NSE_STT_2024 = Source(
    "https://nsearchives.nseindia.com/content/circulars/FATAX63809.pdf",
    "NSE/FATAX/63809: Revision in rates of Securities Transaction Tax (Finance (No. 2) Act, 2024)",
    "2024-09-09",
)
NSE_LEVIES = Source(
    "https://www.nseindia.in/static/invest/first-time-investor-sebi-turnover-fees-stt-other-levies",
    "NSE: SEBI turnover fees, STT and other levies",
    "2026-04-17",
)
NSE_CHARGES_2024 = Source(
    "https://nsearchives.nseindia.com/content/circulars/FA64232.pdf",
    "NSE/FA/64232: Revision in transaction charges (SEBI 'true to label' circular)",
    "2024-09-27",
)
NSE_CHARGES_2026 = Source(
    "https://nsearchives.nseindia.com/content/circulars/FA73061.pdf",
    "NSE/FA/73061: Revision in transaction charges and IPFT contribution",
    "2026-02-27",
)
NSE_STAMP = Source(
    "https://www.nseindia.in/static/invest/first-time-investor-stamp-duty-charges-taxes",
    "NSE: Stamp duty charges (Indian Stamp Act amendment, from 1 Jul 2020)",
    "2023-10-03",
)
SEC_FY2026 = Source(
    "https://www.sec.gov/rules-regulations/fee-rate-advisories/2026-2",
    "SEC Fee Rate Advisory #2 for Fiscal Year 2026",
    "2026-02-27",
)
SEC_FY2025 = Source(
    "https://www.sec.gov/rules-regulations/fee-rate-advisories/2025-2",
    "SEC Fee Rate Advisory #2 for Fiscal Year 2025",
    "2025-04-08",
)
FINRA_SCHEDULE = Source(
    "https://www.finra.org/rules-guidance/rule-filings/sr-finra-2024-019/fee-adjustment-schedule",
    "FINRA SR-FINRA-2024-019 fee adjustment schedule",
    "undated page",
)
FINRA_2024_019 = Source(
    "https://www.finra.org/sites/default/files/2024-11/sr-finra-2024-019.pdf",
    "SR-FINRA-2024-019 rule text (TAF from 1 Jan 2026; replaces $0.000166 / $8.30)",
    "2024-11",
)
FINRA_PAUSE = Source(
    "https://www.finra.org/rules-guidance/rulebooks/corporate-organization/section-1-member-regulatory-fees",
    "FINRA By-Laws Schedule A, Section 1 (SR-FINRA-2026-021: TAF paused 1 Oct-31 Dec 2026)",
    "2026-10-01",
)

# --- Indian components ----------------------------------------------------

GST_BASE = ("brokerage", "exchange_transaction", "sebi", "ipft")


def _pct(text: str) -> Decimal:
    return Decimal(text) / 100


def _sebi() -> Component:
    return Component(
        "sebi",
        "SEBI turnover fee",
        "value",
        Decimal("0.000001"),
        "both",
        NSE_LEVIES,
        note="Rs 10 per crore (0.0001%)",
    )


def _gst() -> Component:
    return Component(
        "gst",
        "GST",
        "gst",
        Decimal("0.18"),
        "both",
        ZERODHA_CHARGES,
        gst_on=GST_BASE,
        note="18% on brokerage + SEBI fee + exchange transaction charges",
    )


def _stamp(rate: str, segment: str) -> Component:
    return Component(
        "stamp_duty",
        "Stamp duty",
        "value",
        _pct(rate),
        "buy",
        NSE_STAMP,
        note=f"{rate}% on buys ({segment}), from 1 Jul 2020",
    )


def _stt(rate: str, side: Side, source: Source, note: str) -> Component:
    return Component(
        "stt",
        "Securities transaction tax (STT)",
        "value",
        _pct(rate),
        side,
        source,
        rounding="unit",
        note=note,
    )


def _exchange(rate: str, source: Source, note: str) -> Component:
    return Component(
        "exchange_transaction",
        "Exchange transaction charge",
        "value",
        _pct(rate),
        "both",
        source,
        note=note,
    )


def _ipft(rate: str, note: str) -> Component:
    return Component(
        "ipft", "NSE IPFT contribution", "value", _pct(rate), "both", NSE_CHARGES_2026, note=note
    )


DP = Component(
    "dp_charge",
    "DP charge (depository)",
    "flat",
    Decimal("15.34"),
    "sell",
    ZERODHA_CHARGES,
    per_scrip_day=True,
    note="Rs 15.34 per scrip per day on sells (Rs 3.5 CDSL + Rs 9.5 Zerodha + "
    "Rs 2.34 GST), whatever the quantity",
)

STT_DELIVERY = _stt(
    "0.1", "both", NSE_STT_2026, "0.1% on buy and sell (unchanged by the Finance Act 2026)"
)
STT_INTRADAY = _stt("0.025", "sell", NSE_STT_2026, "0.025% on sells (unchanged)")

# NSE cash market transaction charge: Rs 2.97 per lakh + IPFT Rs 10 per crore
# from 1 Oct 2024; Rs 306.99 + Rs 0.01 IPFT = Rs 307 per crore from 1 Mar 2026.
NSE_CASH_2024 = (
    _exchange("0.00297", NSE_CHARGES_2024, "Rs 2.97 per lakh each side, from 1 Oct 2024"),
    _ipft("0.0001", "Rs 10 per crore each side (cash), 1 Oct 2024 to 28 Feb 2026"),
)
NSE_CASH_2026 = (
    _exchange(
        "0.00307",
        NSE_CHARGES_2026,
        "Rs 307 per crore each side including Rs 0.01 IPFT, from 1 Mar 2026",
    ),
)
BSE_CASH = _exchange(
    "0.00375", ZERODHA_CHARGES, "BSE 0.00375% (Rs 375 per crore), w.e.f. 1 Dec 2022 per the page"
)

D_2024_10_01 = date(2024, 10, 1)
D_2026_02_28 = date(2026, 2, 28)
D_2026_03_01 = date(2026, 3, 1)
D_2026_03_31 = date(2026, 3, 31)
D_2026_04_01 = date(2026, 4, 1)
D_BSE = date(2022, 12, 1)

BEFORE_NOTE = (
    "Rates before {d} are not on file (no document read confirms them); earlier "
    "fills are priced at {d}'s rates and flagged."
)


def _cash_versions(stt: Component, stamp: Component, *, dp: bool) -> tuple[FeeVersion, ...]:
    tail: tuple[Component, ...] = (_gst(), stamp) + ((DP,) if dp else ())
    return (
        FeeVersion(D_2024_10_01, D_2026_02_28, (stt, *NSE_CASH_2024, _sebi(), *tail)),
        FeeVersion(D_2026_03_01, None, (stt, *NSE_CASH_2026, _sebi(), *tail)),
    )


def _bse_versions(stt: Component, stamp: Component, *, dp: bool) -> tuple[FeeVersion, ...]:
    tail: tuple[Component, ...] = (_gst(), stamp) + ((DP,) if dp else ())
    return (FeeVersion(D_BSE, None, (stt, BSE_CASH, _sebi(), *tail)),)


ZERO_BROKERAGE = BrokerageModel("zero", "No brokerage", "zero")
ZERODHA_DELIVERY = BrokerageModel(
    "zerodha", "Zerodha: equity delivery", "zero", source=ZERODHA_CHARGES
)
ZERODHA_PCT = BrokerageModel(
    "zerodha",
    "Zerodha: 0.03% or Rs 20 per executed order",
    "pct_or_flat",
    pct=_pct("0.03"),
    flat=Decimal(20),
    source=ZERODHA_CHARGES,
)
ZERODHA_FLAT = BrokerageModel(
    "zerodha",
    "Zerodha: flat Rs 20 per executed order",
    "flat",
    flat=Decimal(20),
    source=ZERODHA_CHARGES,
)


def _india(
    name: str,
    label: str,
    segment: str,
    venue: str,
    versions: tuple[FeeVersion, ...],
    broker: BrokerageModel,
    *,
    aliases: tuple[str, ...] = (),
    notes: tuple[str, ...] = (),
) -> FeeSchedule:
    first = min(v.effective_from for v in versions)
    return FeeSchedule(
        name=name,
        label=label,
        currency="INR",
        market="IN",
        segment=segment,
        venue=venue,
        versions=versions,
        brokerage_models={"zerodha": broker, "zero": ZERO_BROKERAGE},
        aliases=aliases,
        notes=(BEFORE_NOTE.format(d=first.isoformat()), *notes),
    )


IN_EQUITY_DELIVERY_NSE = _india(
    "in_equity_delivery_nse",
    "NSE equity delivery",
    "equity_delivery",
    "XNSE",
    _cash_versions(STT_DELIVERY, _stamp("0.015", "delivery"), dp=True),
    ZERODHA_DELIVERY,
    aliases=("in_delivery_nse_2026",),
)
IN_EQUITY_DELIVERY_BSE = _india(
    "in_equity_delivery_bse",
    "BSE equity delivery",
    "equity_delivery",
    "XBOM",
    _bse_versions(STT_DELIVERY, _stamp("0.015", "delivery"), dp=True),
    ZERODHA_DELIVERY,
    aliases=("in_delivery_bse_2026",),
)
IN_EQUITY_INTRADAY_NSE = _india(
    "in_equity_intraday_nse",
    "NSE equity intraday",
    "equity_intraday",
    "XNSE",
    _cash_versions(STT_INTRADAY, _stamp("0.003", "intraday"), dp=False),
    ZERODHA_PCT,
)
IN_EQUITY_INTRADAY_BSE = _india(
    "in_equity_intraday_bse",
    "BSE equity intraday",
    "equity_intraday",
    "XBOM",
    _bse_versions(STT_INTRADAY, _stamp("0.003", "intraday"), dp=False),
    ZERODHA_PCT,
)

FNO_NOTE = (
    "STT before 1 Oct 2024 (futures 0.0125%, options 0.0625%, per NSE/FATAX/63809) is "
    "not used: the NSE transaction charges before 1 Oct 2024 were not confirmed from an "
    "NSE source."
)


def _futures_stt(rate: str, source: Source, note: str) -> Component:
    return _stt(rate, "sell", source, note)


IN_FUTURES_NSE = _india(
    "in_futures_nse",
    "NSE equity futures",
    "futures",
    "XNSE",
    (
        FeeVersion(
            D_2024_10_01,
            D_2026_02_28,
            (
                _futures_stt("0.02", NSE_STT_2024, "0.02% on sells, from 1 Oct 2024"),
                _exchange(
                    "0.00173", NSE_CHARGES_2024, "Rs 1.73 per lakh each side, from 1 Oct 2024"
                ),
                _ipft("0.0001", "Rs 10 per crore each side (futures), 1 Oct 2024 to 28 Feb 2026"),
                _sebi(),
                _gst(),
                _stamp("0.002", "futures"),
            ),
        ),
        FeeVersion(
            D_2026_03_01,
            D_2026_03_31,
            (
                _futures_stt("0.02", NSE_STT_2024, "0.02% on sells, until 31 Mar 2026"),
                _exchange(
                    "0.00183",
                    NSE_CHARGES_2026,
                    "Rs 183 per crore each side including Rs 0.01 IPFT, from 1 Mar 2026",
                ),
                _sebi(),
                _gst(),
                _stamp("0.002", "futures"),
            ),
        ),
        FeeVersion(
            D_2026_04_01,
            None,
            (
                _futures_stt(
                    "0.05", NSE_STT_2026, "0.05% on sells, from 1 Apr 2026 (Finance Act 2026)"
                ),
                _exchange(
                    "0.00183",
                    NSE_CHARGES_2026,
                    "Rs 183 per crore each side including Rs 0.01 IPFT, from 1 Mar 2026",
                ),
                _sebi(),
                _gst(),
                _stamp("0.002", "futures"),
            ),
        ),
    ),
    ZERODHA_PCT,
    notes=(FNO_NOTE, "Price is the futures price; value = price x quantity (lot size x lots)."),
)

IN_OPTIONS_NSE = _india(
    "in_options_nse",
    "NSE equity options (on premium)",
    "options",
    "XNSE",
    (
        FeeVersion(
            D_2024_10_01,
            D_2026_02_28,
            (
                _stt("0.1", "sell", NSE_STT_2024, "0.10% of premium on sells, from 1 Oct 2024"),
                _exchange(
                    "0.03503",
                    NSE_CHARGES_2024,
                    "Rs 35.03 per lakh of premium each side, from 1 Oct 2024",
                ),
                _ipft("0.0005", "Rs 50 per crore of premium each side, 1 Oct 2024 to 28 Feb 2026"),
                _sebi(),
                _gst(),
                _stamp("0.003", "options"),
            ),
        ),
        FeeVersion(
            D_2026_03_01,
            D_2026_03_31,
            (
                _stt("0.1", "sell", NSE_STT_2024, "0.10% of premium on sells, until 31 Mar 2026"),
                _exchange(
                    "0.03553",
                    NSE_CHARGES_2026,
                    "Rs 3,553 per crore of premium each side including Rs 0.01 IPFT",
                ),
                _sebi(),
                _gst(),
                _stamp("0.003", "options"),
            ),
        ),
        FeeVersion(
            D_2026_04_01,
            None,
            (
                _stt(
                    "0.15",
                    "sell",
                    NSE_STT_2026,
                    "0.15% of premium on sells, from 1 Apr 2026 (Finance Act 2026)",
                ),
                _exchange(
                    "0.03553",
                    NSE_CHARGES_2026,
                    "Rs 3,553 per crore of premium each side including Rs 0.01 IPFT",
                ),
                _sebi(),
                _gst(),
                _stamp("0.003", "options"),
            ),
        ),
    ),
    ZERODHA_FLAT,
    notes=(
        FNO_NOTE,
        "Price is the premium per unit; value = premium x quantity (lot size x lots).",
        "STT on exercised options (0.15% of intrinsic value from 1 Apr 2026, 0.125% "
        "before) is not modelled: the simulator does not exercise Indian options.",
    ),
)

# --- US ---------------------------------------------------------------------


def _sec(rate: str, source: Source, note: str) -> Component:
    return Component(
        "sec_section_31",
        "SEC Section 31 fee",
        "value",
        Decimal(rate) / Decimal(1_000_000),
        "sell",
        source,
        note=note,
    )


def _taf(rate: str, cap: str, source: Source, note: str) -> Component:
    return Component(
        "finra_taf",
        "FINRA Trading Activity Fee",
        "per_share",
        Decimal(rate),
        "sell",
        source,
        cap=Decimal(cap),
        note=note,
    )


SEC_27_80 = _sec("27.80", SEC_FY2025, "$27.80 per million of sales, through 13 May 2025")
SEC_ZERO = _sec("0", SEC_FY2026, "$0.00 per million, 14 May 2025 to 3 Apr 2026")
SEC_20_60 = _sec("20.60", SEC_FY2026, "$20.60 per million of sales, from 4 Apr 2026")
TAF_2025 = _taf(
    "0.000166", "8.30", FINRA_2024_019, "$0.000166 per share, max $8.30, to 31 Dec 2025"
)
TAF_2026 = _taf(
    "0.000195", "9.79", FINRA_SCHEDULE, "$0.000195 per share, max $9.79, from 1 Jan 2026"
)
TAF_PAUSED = _taf(
    "0", "0", FINRA_PAUSE, "TAF paused: $0.00, 1 Oct to 31 Dec 2026 (SR-FINRA-2026-021)"
)

US_EQUITY = FeeSchedule(
    name="us_equity",
    label="US equities (SEC Section 31 fee, FINRA TAF)",
    currency="USD",
    market="US",
    segment="equity",
    versions=(
        FeeVersion(
            date(2025, 1, 1),
            date(2025, 5, 13),
            (SEC_27_80, TAF_2025),
            start_confirmed=False,
            notes=(
                "The documents read say when these rates ended, not when they "
                "began; fills before 14 May 2025 use them and are flagged.",
            ),
        ),
        FeeVersion(date(2025, 5, 14), date(2025, 12, 31), (SEC_ZERO, TAF_2025)),
        FeeVersion(date(2026, 1, 1), date(2026, 4, 3), (SEC_ZERO, TAF_2026)),
        FeeVersion(date(2026, 4, 4), date(2026, 9, 30), (SEC_20_60, TAF_2026)),
        FeeVersion(date(2026, 10, 1), date(2026, 12, 31), (SEC_20_60, TAF_PAUSED)),
        FeeVersion(
            date(2027, 1, 1),
            None,
            (SEC_20_60, TAF_2026),
            notes=(
                "TAF $0.000195 / $9.79 is FINRA's scheduled 2027 rate; the SEC rate "
                "holds until the FY2027 advisory.",
            ),
        ),
    ),
    commission_label="commission",
    commission_rounding="micro",
    aliases=("us_equity_2026",),
    notes=("Commission: the run's commission_bps (0 by default), charged both ways.",),
)

NONE = FeeSchedule(name="none", label="No fees (commission only)")

FAMILIES: tuple[FeeSchedule, ...] = (
    NONE,
    US_EQUITY,
    IN_EQUITY_DELIVERY_NSE,
    IN_EQUITY_DELIVERY_BSE,
    IN_EQUITY_INTRADAY_NSE,
    IN_EQUITY_INTRADAY_BSE,
    IN_FUTURES_NSE,
    IN_OPTIONS_NSE,
)

FEE_SCHEDULES: dict[str, FeeSchedule] = {
    **{f.name: f for f in FAMILIES},
    **{alias: f for f in FAMILIES for alias in f.aliases},
}

# Older names kept as module attributes for callers that import them.
US_EQUITY_2026 = US_EQUITY
IN_DELIVERY_NSE_2026 = IN_EQUITY_DELIVERY_NSE
IN_DELIVERY_BSE_2026 = IN_EQUITY_DELIVERY_BSE

BROKERAGE_MODELS = ("zerodha", "zero")


class UnknownFeeScheduleError(LookupError):
    pass


def get_fee_schedule(name: str) -> FeeSchedule:
    try:
        return FEE_SCHEDULES[name]
    except KeyError as exc:
        raise UnknownFeeScheduleError(f"Unknown fee schedule {name!r}") from exc
