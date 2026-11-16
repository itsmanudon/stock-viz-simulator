"""Portfolio exposure by sector, country and currency (Phase 8.2).

Weights are shares of NAV in the display currency: equities at market value,
cash under its own currency. Open options are listed beside the weights at
their delta-adjusted notional (the shares of the underlying they move like),
which is exposure, not value, so it is never added into the NAV weights.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal

from sqlmodel import Session, col, select

from stockviz.models import Symbol
from stockviz.models.instrument import Instrument
from stockviz.services.instruments import instrument_of
from stockviz.services.trading.portfolio import PortfolioValuation

DIMENSIONS: tuple[str, ...] = ("sector", "country", "currency")
UNCLASSIFIED = "Not recorded"
CASH = "Cash"

EXPOSURE_METHOD = "share_of_nav"
EXPOSURE_BASIS = (
    "equities at market value and cash by currency, as a share of NAV; open options "
    "at delta-adjusted notional, shown beside and not added in"
)


@dataclass(frozen=True, slots=True)
class Classification:
    sector: str | None
    country: str | None
    currency: str


@dataclass(slots=True)
class ExposureBucket:
    key: str
    equity_value: Decimal = Decimal(0)
    cash_value: Decimal = Decimal(0)
    options_delta: Decimal = Decimal(0)
    weight_pct: float = 0.0
    options_delta_pct: float = 0.0


@dataclass(frozen=True, slots=True)
class Exposure:
    dimension: str
    buckets: list[ExposureBucket] = field(default_factory=list)


def classifications(session: Session, tickers: list[str]) -> dict[str, Classification]:
    """Sector, instrument country and currency per ticker, in one query."""
    if not tickers:
        return {}
    rows = session.exec(
        select(Symbol.ticker, Symbol.sector, Symbol.currency, Instrument.country)
        .outerjoin(Instrument, col(Instrument.id) == instrument_of(Symbol.ticker))
        .where(col(Symbol.ticker).in_(tickers))
    ).all()
    return {
        ticker: Classification(sector, country, currency or "USD")
        for ticker, sector, currency, country in rows
    }


def _key(info: Classification | None, dimension: str, fallback_currency: str) -> str:
    if info is None:
        return fallback_currency if dimension == "currency" else UNCLASSIFIED
    value = getattr(info, dimension)
    return value or UNCLASSIFIED


def compute_exposure(
    valuation: PortfolioValuation, info: Mapping[str, Classification]
) -> list[Exposure]:
    nav = valuation.total_value
    out: list[Exposure] = []
    for dimension in DIMENSIONS:
        buckets: dict[str, ExposureBucket] = {}

        def bucket(key: str, buckets: dict[str, ExposureBucket] = buckets) -> ExposureBucket:
            return buckets.setdefault(key, ExposureBucket(key))

        for position in valuation.positions:
            key = _key(info.get(position.ticker), dimension, position.currency)
            bucket(key).equity_value += position.market_value
        for held in valuation.option_positions:
            key = _key(info.get(held.ticker), dimension, held.currency)
            bucket(key).options_delta += held.delta_notional
        for cash in valuation.cash_by_currency:
            if cash.value == 0:
                continue
            key = cash.currency if dimension == "currency" else CASH
            bucket(key).cash_value += cash.value
        for item in buckets.values():
            if nav > 0:
                item.weight_pct = float((item.equity_value + item.cash_value) / nav * 100)
                item.options_delta_pct = float(item.options_delta / nav * 100)
        ordered = sorted(
            buckets.values(),
            key=lambda b: (b.key == CASH, -(b.equity_value + b.cash_value), b.key),
        )
        out.append(Exposure(dimension, ordered))
    return out
