"""The unified screener (Phase 6.2).

One query path for ``/v1/screener`` (paged) and the original
``/v1/symbols/screen`` (a list):

1. SQL filters on the nightly snapshot (``symbol_metrics``) joined to the
   symbol and its instrument (market = country, exchange = venue MIC,
   currency).
2. Momentum, when asked for, is computed for **every** candidate before any
   limit (audit RS-5: the limit used to come first, alphabetically, so a
   momentum screen only ever saw the first 200 tickers).
3. Sort on any result column, missing values last, then page.

The universe is a few hundred symbols, so steps 2-3 run in memory. Values
stay ``None`` when unknown; nothing is reported as 0 (RS-4).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from sqlmodel import Session, col, select

from stockviz.models import Symbol, SymbolMetrics
from stockviz.models.instrument import Instrument
from stockviz.services.instruments import instrument_of
from stockviz.services.recent_bars import recent_closes

NEAR_52W_THRESHOLD = Decimal("0.05")
MAX_MOMENTUM_DAYS = 252

FUNDAMENTAL_COLUMNS = (
    "pe",
    "pb",
    "ps",
    "ev_ebitda",
    "dividend_yield",
    "market_cap_usd",
    "net_margin",
    "roe",
    "debt_to_equity",
    "revenue_growth",
)
"""Phase 6.5: valuation columns in the snapshot, each with an optional range."""

SORT_KEYS = (
    "ticker",
    "name",
    "market",
    "last_close",
    "rsi_14",
    "momentum_pct",
    "pct_from_52w_high",
    "sma_50_gap_pct",
    "sma_200_gap_pct",
    "atr_pct_14",
    "hv_20",
    "avg_volume_20",
    "sentiment_7d",
    *FUNDAMENTAL_COLUMNS,
)


@dataclass
class ScreenQuery:
    markets: list[str] = field(default_factory=list)  # ISO countries, e.g. US, IN
    exchanges: list[str] = field(default_factory=list)  # MICs, e.g. XNAS, XNSE
    currencies: list[str] = field(default_factory=list)
    sector: str | None = None
    rsi_min: float | None = None
    rsi_max: float | None = None
    momentum_days: int | None = None
    momentum_min: float | None = None
    momentum_max: float | None = None
    near_52w_high: bool = False
    near_52w_low: bool = False
    above_sma_50: bool | None = None
    above_sma_200: bool | None = None
    hv_min: float | None = None
    hv_max: float | None = None
    atr_pct_min: float | None = None
    atr_pct_max: float | None = None
    sentiment_min: float | None = None
    sentiment_max: float | None = None
    # Phase 6.5: column -> (min, max) for any FUNDAMENTAL_COLUMNS entry.
    fundamentals: dict[str, tuple[float | None, float | None]] = field(default_factory=dict)
    sort: str = "ticker"
    descending: bool = False
    offset: int = 0
    limit: int = 50


@dataclass
class ScreenRow:
    ticker: str
    name: str
    sector: str | None
    exchange: str | None
    market: str | None
    mic: str | None
    currency: str
    last_close: Decimal | None
    as_of: date | None
    rsi_14: float | None
    momentum_pct: float | None
    momentum_days: int | None
    high_52w: Decimal | None
    low_52w: Decimal | None
    pct_from_52w_high: float | None
    sma_50: float | None
    sma_200: float | None
    sma_50_gap_pct: float | None
    sma_200_gap_pct: float | None
    atr_pct_14: float | None
    hv_20: float | None
    avg_volume_20: float | None
    sentiment_7d: float | None
    pe: float | None = None
    pb: float | None = None
    ps: float | None = None
    ev_ebitda: float | None = None
    dividend_yield: float | None = None
    market_cap_usd: float | None = None
    net_margin: float | None = None
    roe: float | None = None
    debt_to_equity: float | None = None
    revenue_growth: float | None = None

    def get(self, key: str) -> Any:
        return getattr(self, key)


def _gap(close: Decimal | None, level: float | None) -> float | None:
    if close is None or level in (None, 0):
        return None
    return (float(close) / level - 1) * 100


def _momentum(session: Session, tickers: list[str], days: int) -> dict[str, float | None]:
    closes = recent_closes(session, tickers, limit_per_ticker=days + 1)
    out: dict[str, float | None] = {}
    for ticker in tickers:
        values = closes.get(ticker, [])
        now = values[-1] if values else None
        then = values[0] if len(values) == days + 1 else None
        out[ticker] = (
            float((now - then) / then * 100) if now is not None and then not in (None, 0) else None
        )
    return out


def run_screen(session: Session, q: ScreenQuery) -> tuple[list[ScreenRow], int]:
    """Rows on the requested page, and how many matched in all."""
    stmt = (
        select(SymbolMetrics, Symbol, Instrument)
        .join(Symbol, col(Symbol.ticker) == col(SymbolMetrics.ticker))
        .join(Instrument, col(Instrument.id) == instrument_of(Symbol.ticker), isouter=True)
        .where(col(Symbol.is_active), col(Symbol.ticker).not_like("^%"))
    )
    m = SymbolMetrics
    if q.markets:
        stmt = stmt.where(col(Instrument.country).in_([x.upper() for x in q.markets]))
    if q.exchanges:
        stmt = stmt.where(col(Instrument.mic).in_([x.upper() for x in q.exchanges]))
    if q.currencies:
        stmt = stmt.where(col(Symbol.currency).in_([x.upper() for x in q.currencies]))
    if q.sector is not None:
        stmt = stmt.where(col(Symbol.sector) == q.sector)
    for column, low, high in (
        (m.rsi_14, q.rsi_min, q.rsi_max),
        (m.hv_20, q.hv_min, q.hv_max),
        (m.atr_pct_14, q.atr_pct_min, q.atr_pct_max),
        (m.sentiment_7d, q.sentiment_min, q.sentiment_max),
    ):
        if low is not None:
            stmt = stmt.where(col(column) >= low)
        if high is not None:
            stmt = stmt.where(col(column) <= high)
    for name, (low, high) in q.fundamentals.items():
        if name not in FUNDAMENTAL_COLUMNS:
            continue
        column = getattr(m, name)
        if low is not None:
            stmt = stmt.where(col(column) >= low)
        if high is not None:
            stmt = stmt.where(col(column) <= high)
    if q.near_52w_high:
        stmt = stmt.where(
            col(m.high_52w).is_not(None),
            col(m.last_close) >= col(m.high_52w) * (Decimal(1) - NEAR_52W_THRESHOLD),
        )
    if q.near_52w_low:
        stmt = stmt.where(
            col(m.low_52w).is_not(None),
            col(m.last_close) <= col(m.low_52w) * (Decimal(1) + NEAR_52W_THRESHOLD),
        )
    for flag, level in ((q.above_sma_50, m.sma_50), (q.above_sma_200, m.sma_200)):
        if flag is not None:
            stmt = stmt.where(col(level).is_not(None))
            stmt = stmt.where(
                col(m.last_close) > col(level) if flag else col(m.last_close) <= col(level)
            )

    candidates = list(session.exec(stmt).all())
    momentum: dict[str, float | None] = {}
    if q.momentum_days is not None:
        momentum = _momentum(session, [s.ticker for _m, s, _i in candidates], q.momentum_days)

    rows: list[ScreenRow] = []
    for metrics, symbol, instrument in candidates:
        mom = momentum.get(symbol.ticker) if q.momentum_days is not None else None
        if q.momentum_days is not None:
            if mom is None:
                continue
            if q.momentum_min is not None and mom < q.momentum_min:
                continue
            if q.momentum_max is not None and mom > q.momentum_max:
                continue
        close, high = metrics.last_close, metrics.high_52w
        rows.append(
            ScreenRow(
                ticker=symbol.ticker,
                name=symbol.name,
                sector=symbol.sector,
                exchange=symbol.exchange,
                market=instrument.country if instrument else None,
                mic=instrument.mic if instrument else None,
                currency=symbol.currency or "USD",
                last_close=close,
                as_of=metrics.as_of,
                rsi_14=metrics.rsi_14,
                momentum_pct=mom,
                momentum_days=q.momentum_days,
                high_52w=high,
                low_52w=metrics.low_52w,
                pct_from_52w_high=_gap(close, float(high) if high else None),
                sma_50=metrics.sma_50,
                sma_200=metrics.sma_200,
                sma_50_gap_pct=_gap(close, metrics.sma_50),
                sma_200_gap_pct=_gap(close, metrics.sma_200),
                atr_pct_14=metrics.atr_pct_14,
                hv_20=metrics.hv_20,
                avg_volume_20=metrics.avg_volume_20,
                sentiment_7d=metrics.sentiment_7d,
                **{name: getattr(metrics, name) for name in FUNDAMENTAL_COLUMNS},
            )
        )

    key = q.sort if q.sort in SORT_KEYS else "ticker"
    present = [r for r in rows if r.get(key) is not None]
    missing = [r for r in rows if r.get(key) is None]
    present.sort(key=lambda r: (r.get(key), r.ticker), reverse=q.descending)
    missing.sort(key=lambda r: r.ticker)
    ordered = present + missing  # missing values last, whatever the direction
    return ordered[q.offset : q.offset + q.limit], len(ordered)
