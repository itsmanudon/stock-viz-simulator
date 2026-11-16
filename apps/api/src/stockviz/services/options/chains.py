"""Option-chain snapshots and the implied volatility they give (Phase 9.6).

``stockviz.cli options-snapshot`` runs nightly after the ingest: for each US
stock in the universe it fetches the listed chain for the nearest
``MAX_EXPIRIES`` expiries from yfinance (free, unofficial, rate-limited),
and stores every contract with the price used (bid-ask mid when both are
quoted and the ask is not below the bid, else the last trade) and the
implied volatility solved from it against that day's stored close.

Pricing then uses those implied volatilities: ``chain_volatility`` returns
the stored IV of the nearest listed contract of the same type (expiry
first, then strike) from the latest snapshot no older than
``MAX_SNAPSHOT_AGE_DAYS``, provided the listed expiry is within
``MAX_EXPIRY_GAP_DAYS`` of the one asked for and the strike within
``MAX_STRIKE_GAP`` of it; otherwise pricing falls back to the 30-session
historical volatility and says so. History starts the day collection
starts: nothing before it is reconstructed.
"""

from __future__ import annotations

import logging
import math
import time as _time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date as date_type
from datetime import datetime, timedelta
from decimal import Decimal

from sqlmodel import Session, col, delete, select

from stockviz.models import PriceBar
from stockviz.models.option_quote import OptionChainQuote
from stockviz.services.instruments import instrument_ids, instrument_of
from stockviz.services.options.pricing import RISK_FREE_RATES, implied_volatility

logger = logging.getLogger(__name__)

MAX_EXPIRIES = 4
MAX_SNAPSHOT_AGE_DAYS = 5
MAX_EXPIRY_GAP_DAYS = 45
MAX_STRIKE_GAP = 0.10
"""A listed strike more than 10% from the one asked for is not used."""


@dataclass(frozen=True, slots=True)
class ChainRow:
    expiry: date_type
    strike: Decimal
    option_type: str  # "call" | "put"
    bid: Decimal | None
    ask: Decimal | None
    last: Decimal | None
    volume: int | None = None
    open_interest: int | None = None


ChainFetch = Callable[[str], list[ChainRow]]


def _dec(value: object) -> Decimal | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or number < 0:
        return None
    return Decimal(str(round(number, 6)))


def _int(value: object) -> int | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return None if math.isnan(number) else int(number)


def yfinance_chain(ticker: str, *, max_expiries: int = MAX_EXPIRIES) -> list[ChainRow]:
    """The listed chain for the nearest ``max_expiries`` expiries (network)."""
    import yfinance as yf

    handle = yf.Ticker(ticker)
    rows: list[ChainRow] = []
    for raw in list(handle.options)[:max_expiries]:
        expiry = date_type.fromisoformat(raw)
        chain = handle.option_chain(raw)
        for option_type, frame in (("call", chain.calls), ("put", chain.puts)):
            for record in frame.to_dict("records"):
                strike = _dec(record.get("strike"))
                if strike is None or strike <= 0:
                    continue
                rows.append(
                    ChainRow(
                        expiry=expiry,
                        strike=strike,
                        option_type=option_type,
                        bid=_dec(record.get("bid")),
                        ask=_dec(record.get("ask")),
                        last=_dec(record.get("lastPrice")),
                        volume=_int(record.get("volume")),
                        open_interest=_int(record.get("openInterest")),
                    )
                )
    return rows


def _price(row: ChainRow) -> Decimal | None:
    if row.bid and row.ask and row.bid > 0 and row.ask >= row.bid:
        return ((row.bid + row.ask) / 2).quantize(Decimal("0.000001"))
    if row.last and row.last > 0:
        return row.last
    return None


def _close_on(session: Session, ticker: str, day: date_type) -> Decimal | None:
    bar = session.exec(
        select(PriceBar)
        .where(
            PriceBar.instrument_id == instrument_of(ticker),
            PriceBar.interval == "1d",
            PriceBar.ts < datetime.combine(day + timedelta(days=1), datetime.min.time()),
        )
        .order_by(col(PriceBar.ts).desc())
        .limit(1)
    ).first()
    return bar.close if bar is not None else None


def store_snapshot(
    session: Session, ticker: str, rows: list[ChainRow], *, snapshot_date: date_type
) -> int:
    """Replace ``ticker``'s snapshot for ``snapshot_date`` with ``rows``. Returns rows stored.

    A rerun the same day replaces the day's rows, so it changes nothing twice.
    The implied volatility is solved against the latest stored close on or
    before that day; without one nothing is stored.
    """
    ids = instrument_ids(session, [ticker])
    if ticker not in ids:
        return 0
    spot = _close_on(session, ticker, snapshot_date)
    if spot is None:
        return 0
    instrument_id = ids[ticker]
    session.exec(  # type: ignore[call-overload]
        delete(OptionChainQuote).where(
            col(OptionChainQuote.instrument_id) == instrument_id,
            col(OptionChainQuote.snapshot_date) == snapshot_date,
        )
    )
    stored = 0
    rate = RISK_FREE_RATES["USD"]
    seen: set[tuple[date_type, Decimal, str]] = set()
    for row in rows:
        key = (row.expiry, row.strike, row.option_type)
        years = (row.expiry - snapshot_date).days / 365.0
        if key in seen or years <= 0:
            continue
        seen.add(key)
        price = _price(row)
        iv = None
        if price is not None:
            iv = implied_volatility(
                price=float(price),
                spot=float(spot),
                strike=float(row.strike),
                time_to_expiry_years=years,
                risk_free_rate=rate,
                option_type=row.option_type,
            ).volatility
        session.add(
            OptionChainQuote(
                instrument_id=instrument_id,
                snapshot_date=snapshot_date,
                expiry=row.expiry,
                strike=row.strike,
                option_type=row.option_type,
                bid=row.bid,
                ask=row.ask,
                last=row.last,
                price=price,
                implied_volatility=iv,
                volume=row.volume,
                open_interest=row.open_interest,
            )
        )
        stored += 1
    session.commit()
    return stored


def snapshot_all(
    session: Session,
    tickers: list[str],
    *,
    snapshot_date: date_type,
    fetch: ChainFetch,
    pause_seconds: float = 0.3,
) -> tuple[int, list[str]]:
    """Fetch and store each ticker's chain. Returns (rows stored, tickers that failed).

    One ticker failing (no listed options, a provider error) never stops the
    rest; the pause keeps the run polite to the free provider.
    """
    stored = 0
    failed: list[str] = []
    for index, ticker in enumerate(tickers):
        if index and pause_seconds:
            _time.sleep(pause_seconds)
        try:
            rows = fetch(ticker)
        except Exception as exc:
            session.rollback()
            logger.warning("options-snapshot: %s failed: %s", ticker, exc)
            failed.append(ticker)
            continue
        stored += store_snapshot(session, ticker, rows, snapshot_date=snapshot_date)
    return stored, failed


@dataclass(frozen=True, slots=True)
class ChainVolatility:
    volatility: float
    snapshot_date: date_type
    expiry: date_type
    strike: Decimal

    @property
    def method(self) -> str:
        return (
            f"implied volatility from the {self.snapshot_date.isoformat()} option chain, "
            f"nearest listed contract ({self.expiry.isoformat()}, strike {self.strike:,.2f})"
        )


def chain_volatility(
    session: Session,
    ticker: str,
    *,
    option_type: str,
    strike: Decimal,
    expiry: date_type,
    asof: date_type,
) -> ChainVolatility | None:
    """The stored IV for the nearest listed contract, or None to fall back."""
    latest = session.exec(
        select(col(OptionChainQuote.snapshot_date))
        .where(
            OptionChainQuote.instrument_id == instrument_of(ticker),
            OptionChainQuote.snapshot_date <= asof,
        )
        .order_by(col(OptionChainQuote.snapshot_date).desc())
        .limit(1)
    ).first()
    if latest is None or (asof - latest).days > MAX_SNAPSHOT_AGE_DAYS:
        return None
    rows = session.exec(
        select(OptionChainQuote).where(
            OptionChainQuote.instrument_id == instrument_of(ticker),
            OptionChainQuote.snapshot_date == latest,
            OptionChainQuote.option_type == option_type,
            col(OptionChainQuote.implied_volatility).is_not(None),
        )
    ).all()
    if not rows:
        return None
    best = min(rows, key=lambda r: (abs((r.expiry - expiry).days), abs(float(r.strike - strike))))
    if abs((best.expiry - expiry).days) > MAX_EXPIRY_GAP_DAYS:
        return None
    if abs(float(best.strike - strike)) > MAX_STRIKE_GAP * float(strike):
        return None
    assert best.implied_volatility is not None
    return ChainVolatility(
        volatility=best.implied_volatility,
        snapshot_date=latest,
        expiry=best.expiry,
        strike=best.strike,
    )


@dataclass(frozen=True, slots=True)
class SurfacePoint:
    strike: Decimal
    call_iv: float | None
    put_iv: float | None


def surface(
    session: Session, ticker: str, *, asof: date_type
) -> tuple[date_type, list[tuple[date_type, list[SurfacePoint]]]] | None:
    """The latest snapshot's implied volatility by expiry and strike, or None."""
    latest = session.exec(
        select(col(OptionChainQuote.snapshot_date))
        .where(
            OptionChainQuote.instrument_id == instrument_of(ticker),
            OptionChainQuote.snapshot_date <= asof,
        )
        .order_by(col(OptionChainQuote.snapshot_date).desc())
        .limit(1)
    ).first()
    if latest is None:
        return None
    rows = session.exec(
        select(OptionChainQuote).where(
            OptionChainQuote.instrument_id == instrument_of(ticker),
            OptionChainQuote.snapshot_date == latest,
        )
    ).all()
    grid: dict[date_type, dict[Decimal, dict[str, float | None]]] = {}
    for row in rows:
        grid.setdefault(row.expiry, {}).setdefault(row.strike, {})[row.option_type] = (
            row.implied_volatility
        )
    expiries = [
        (
            expiry,
            [
                SurfacePoint(strike=k, call_iv=v.get("call"), put_iv=v.get("put"))
                for k, v in sorted(strikes.items())
            ],
        )
        for expiry, strikes in sorted(grid.items())
    ]
    return latest, expiries
