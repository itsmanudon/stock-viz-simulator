"""Which fee schedule applies by default, and the schedules as API shapes (A4.2).

**Default on for Indian symbols.** Live paper fills, backtests (``auto``)
and, once replay trades in rupees (A4.6), replay use the venue's equity
delivery schedule: NSE (``XNSE``) and BSE (``XBOM``). Every other market
defaults to ``none``: US listings keep ``us_equity`` (SEC Section 31 and
FINRA TAF) as an opt-in for backtests, as before A4.2, so live US cash maths
is unchanged.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

from stockviz.schemas import (
    BrokerageOut,
    CostsOut,
    FeeComponentOut,
    FeeScheduleOut,
    FeeSchedulesOut,
    FeeSourceOut,
    FeeVersionOut,
    LiquidityOut,
)
from stockviz.services.markets.calendar import venue_for_ticker, venue_zone
from stockviz.services.simulation.fees import (
    BROKERAGE_MODELS,
    FAMILIES,
    BrokerageModel,
    Component,
    FeeSchedule,
    FeeVersion,
    Source,
    get_fee_schedule,
)

DEFAULT_BY_VENUE: dict[str, str] = {
    "XNSE": "in_equity_delivery_nse",
    "XBOM": "in_equity_delivery_bse",
}
DEFAULT_OTHER = "none"
INDIAN_VENUES = frozenset(DEFAULT_BY_VENUE)

PRICE_BANDS_NOTE = (
    "Price bands (circuit limits) and the T2T, ASM and F&O ban lists were not checked: "
    "StockViz does not hold that exchange data yet, so a fill on a bar locked at its band "
    "would not be refused."
)
ADV_NOTE = (
    "Each buy (or short) fills at most {pct}% of the 20-day average traded value (close x "
    "volume of the 20 bars before the fill bar); the rest is not filled. Exits are not capped."
)
ADV_OFF_NOTE = "No liquidity cap: fills of any size against the bar's volume."


def default_schedule_name(ticker: str) -> str:
    return DEFAULT_BY_VENUE.get(venue_for_ticker(ticker), DEFAULT_OTHER)


def fee_date(ticker: str, instant: datetime) -> date:
    """The fill's date for fee purposes: ``instant`` in the venue's time zone
    (a rate change takes effect at the venue's midnight)."""
    aware = instant if instant.tzinfo is not None else instant.replace(tzinfo=UTC)
    return aware.astimezone(venue_zone(venue_for_ticker(ticker))).date()


def day_bounds_utc(ticker: str, day: date) -> tuple[datetime, datetime]:
    """The venue day ``day`` as a naive-UTC [start, end) range (trade ``ts``)."""
    zone = venue_zone(venue_for_ticker(ticker))
    start = datetime.combine(day, time.min, tzinfo=zone).astimezone(UTC).replace(tzinfo=None)
    return start, start + timedelta(days=1)


def resolve_fee_schedule(name: str, ticker: str) -> str:
    """``auto`` -> the ticker's market default; any other name is returned as is."""
    return default_schedule_name(ticker) if name == "auto" else name


def is_indian(ticker: str) -> bool:
    return venue_for_ticker(ticker) in INDIAN_VENUES


def source_out(source: Source) -> FeeSourceOut:
    return FeeSourceOut(
        url=source.url, title=source.title, date=source.date, read_on=source.read_on
    )


def component_out(c: Component) -> FeeComponentOut:
    return FeeComponentOut(
        key=c.key,
        label=c.label,
        kind=c.kind,
        rate=c.rate,
        rate_text=c.rate_text(),
        side=c.side,
        cap=c.cap,
        gst_on=list(c.gst_on),
        per_scrip_day=c.per_scrip_day,
        note=c.note,
        source=source_out(c.source),
    )


def version_out(v: FeeVersion, fills: int | None = None) -> FeeVersionOut:
    return FeeVersionOut(
        effective_from=v.effective_from,
        effective_to=v.effective_to,
        start_confirmed=v.start_confirmed,
        components=[component_out(c) for c in v.components],
        notes=list(v.notes),
        fills=fills,
    )


def brokerage_out(model: BrokerageModel) -> BrokerageOut:
    return BrokerageOut(
        key=model.key,
        label=model.label,
        rate_text=model.rate_text(),
        source=source_out(model.source) if model.source else None,
    )


def schedule_out(f: FeeSchedule) -> FeeScheduleOut:
    return FeeScheduleOut(
        name=f.name,
        aliases=list(f.aliases),
        label=f.label or f.name,
        currency=f.currency,
        market=f.market,
        segment=f.segment,
        venue=f.venue,
        coverage_from=f.coverage_from,
        brokerage=[brokerage_out(m) for m in f.brokerage_models.values()],
        versions=[version_out(v) for v in sorted(f.versions, key=lambda v: v.effective_from)],
        notes=list(f.notes),
        default_for=sorted(v for v, n in DEFAULT_BY_VENUE.items() if n == f.name),
    )


def schedules_out() -> FeeSchedulesOut:
    return FeeSchedulesOut(
        schedules=[schedule_out(f) for f in FAMILIES],
        defaults=dict(DEFAULT_BY_VENUE),
        default_other=DEFAULT_OTHER,
        brokerage_models=list(BROKERAGE_MODELS),
        notes=[
            "Each fill uses the version in force on its fill date.",
            "Indian symbols get their venue's equity delivery schedule by default (live paper "
            "fills, backtests); other markets default to none.",
            "Rates were copied from the documents listed with each component; a period or "
            "segment no document read confirms is left out.",
            PRICE_BANDS_NOTE,
        ],
    )


def costs_out(
    *,
    requested: str,
    resolved: str,
    brokerage: str,
    commission_bps: float,
    fee_versions: dict[date, int],
    fills_before_coverage: int,
    indian: bool,
) -> CostsOut:
    f = get_fee_schedule(resolved)
    model = f.brokerage_models.get(brokerage)
    by_start = {v.effective_from: v for v in f.versions}
    return CostsOut(
        schedule=f.name,
        requested=requested,
        label=f.label or f.name,
        currency=f.currency,
        segment=f.segment,
        brokerage=brokerage_out(model) if model else None,
        commission_bps=commission_bps,
        coverage_from=f.coverage_from,
        fills_before_coverage=fills_before_coverage,
        versions=[version_out(by_start[d], n) for d, n in sorted(fee_versions.items())],
        notes=list(f.notes),
        price_bands_checked=False,
        price_bands_note=PRICE_BANDS_NOTE if indian else None,
    )


def liquidity_out(
    adv_cap_pct: float | None, *, partial: int, skipped: int, unknown: int
) -> LiquidityOut:
    return LiquidityOut(
        adv_cap_pct=adv_cap_pct,
        partial_entries=partial,
        skipped_entries=skipped,
        not_capped=unknown,
        note=ADV_NOTE.format(pct=f"{adv_cap_pct:g}") if adv_cap_pct else ADV_OFF_NOTE,
    )


__all__ = [
    "DEFAULT_BY_VENUE",
    "PRICE_BANDS_NOTE",
    "costs_out",
    "day_bounds_utc",
    "default_schedule_name",
    "fee_date",
    "is_indian",
    "liquidity_out",
    "resolve_fee_schedule",
    "schedules_out",
]
