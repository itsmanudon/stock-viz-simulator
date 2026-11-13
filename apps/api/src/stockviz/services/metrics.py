"""Refresh the precomputed ``symbol_metrics`` rows.

Runs once a day after the price refresh, and has a matching CLI subcommand like
every other scheduled job. Computing these once and reading them back is what
turns the screener from "scan the whole bar table per request" into a single
indexed query.
"""

from __future__ import annotations

import logging
import math
from datetime import date as date_type

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import Session, col, select

from stockviz._time import utcnow
from stockviz.models import PriceBar, Symbol, SymbolMetrics
from stockviz.services.indicators import compute_rsi, engine
from stockviz.services.instruments import instrument_ids, instrument_of

logger = logging.getLogger(__name__)

LOOKBACK_BARS = 260
"""A trading year plus a little: covers RSI(14)'s warm-up (140 bars) and the
52-week range."""

YEAR_SESSIONS = 252
"""The 52-week range is the highest high and lowest low of the last 252
sessions (audit RS-14). The stock page computes the same thing from bars."""

RSI_PERIOD = 14


def _last(series) -> float | None:
    value = series.iloc[-1] if len(series) else None
    return None if value is None or math.isnan(value) else float(value)


def _snapshot(bars: list[PriceBar]) -> dict[str, float | None]:
    """Screener columns from the indicator engine (Phase 6.2)."""
    frame = engine.frame([(b.ts, b.open, b.high, b.low, b.close, b.volume) for b in bars])
    close = float(bars[-1].close)
    atr_14 = _last(engine.atr(frame, 14)["value"])
    return {
        "sma_50": _last(engine.sma(frame, 50)["value"]),
        "sma_200": _last(engine.sma(frame, 200)["value"]),
        "atr_pct_14": atr_14 / close * 100 if atr_14 is not None and close else None,
        "hv_20": _last(engine.hv(frame, 20)["value"]),
        "avg_volume_20": _last(frame["volume"].rolling(20, min_periods=20).mean()),
    }


def _fundamentals(session: Session, ticker: str, day) -> dict[str, float | None]:
    """Valuation columns for the screener (Phase 6.5), as known on ``day``."""
    from stockviz.services.fundamentals.valuation import valuation
    from stockviz.services.trading.fx import latest_rate

    v = valuation(session, ticker, day)
    mcap = v.value("market_cap")
    mcap_usd = None
    if mcap is not None and v.reporting_currency:
        try:
            mcap_usd = mcap * float(latest_rate(session, v.reporting_currency, on_or_before=day))
        except LookupError:
            mcap_usd = None
    return {
        "pe": v.value("pe"),
        "pb": v.value("pb"),
        "ps": v.value("ps"),
        "ev_ebitda": v.value("ev_ebitda"),
        "dividend_yield": v.value("dividend_yield"),
        "market_cap_usd": mcap_usd,
        "net_margin": v.value("net_margin"),
        "roe": v.value("roe"),
        "debt_to_equity": v.value("debt_to_equity"),
        "revenue_growth": v.value("revenue_growth"),
    }


def compute_for_ticker(session: Session, ticker: str) -> SymbolMetrics | None:
    """Build (but don't persist) the metrics row for one symbol.

    Returns ``None`` when the symbol has no bars at all — there is nothing
    meaningful to store and the screener should not surface it.
    """
    bars = list(
        session.exec(
            select(PriceBar)
            .where(PriceBar.instrument_id == instrument_of(ticker), PriceBar.interval == "1d")
            .order_by(PriceBar.ts.desc())  # type: ignore[attr-defined]
            .limit(LOOKBACK_BARS)
        ).all()
    )
    if not bars:
        return None
    bars.reverse()  # oldest first

    closes = [b.close for b in bars]
    rsi_points = compute_rsi([(b.ts, b.close) for b in bars], period=RSI_PERIOD)
    rsi = rsi_points[-1].value if rsi_points else None
    snap = _snapshot(bars)

    row = SymbolMetrics(
        ticker=ticker,
        as_of=bars[-1].ts.date(),
        last_close=closes[-1],
        rsi_14=rsi,
        high_52w=max(b.high for b in bars[-YEAR_SESSIONS:]),
        low_52w=min(b.low for b in bars[-YEAR_SESSIONS:]),
        computed_at=utcnow(),
        sma_50=snap["sma_50"],
        sma_200=snap["sma_200"],
        atr_pct_14=snap["atr_pct_14"],
        hv_20=snap["hv_20"],
        avg_volume_20=snap["avg_volume_20"],
    )
    for name, value in _fundamentals(session, ticker, bars[-1].ts.date()).items():
        setattr(row, name, value)
    return row


def refresh_symbol_metrics(
    session: Session,
    *,
    tickers: list[str] | None = None,
    commit: bool = True,
) -> int:
    """Recompute and upsert metrics for ``tickers`` (default: all active symbols).

    Sentiment columns are left untouched — they are owned by the sentiment
    aggregate pass, which runs on its own cadence after news ingest.
    """
    if tickers is None:
        tickers = list(session.exec(select(Symbol.ticker).where(Symbol.is_active)).all())

    written = 0
    for ticker in tickers:
        row = compute_for_ticker(session, ticker)
        if row is None:
            continue
        _upsert(session, row)
        written += 1
    if commit:
        session.commit()
    logger.info("refresh_symbol_metrics: wrote %d rows", written)
    return written


def _upsert(session: Session, row: SymbolMetrics) -> None:
    """Insert-or-update one metrics row, preserving the sentiment columns."""
    instrument_id = instrument_ids(session, [row.ticker]).get(row.ticker)
    values = {
        "ticker": row.ticker,
        "instrument_id": instrument_id,
        "as_of": row.as_of,
        "last_close": row.last_close,
        "rsi_14": row.rsi_14,
        "high_52w": row.high_52w,
        "low_52w": row.low_52w,
        "sma_50": row.sma_50,
        "sma_200": row.sma_200,
        "atr_pct_14": row.atr_pct_14,
        "hv_20": row.hv_20,
        "avg_volume_20": row.avg_volume_20,
        "pe": row.pe,
        "pb": row.pb,
        "ps": row.ps,
        "ev_ebitda": row.ev_ebitda,
        "dividend_yield": row.dividend_yield,
        "market_cap_usd": row.market_cap_usd,
        "net_margin": row.net_margin,
        "roe": row.roe,
        "debt_to_equity": row.debt_to_equity,
        "revenue_growth": row.revenue_growth,
        "computed_at": row.computed_at,
    }

    if session.bind is not None and session.bind.dialect.name == "postgresql":
        stmt = pg_insert(SymbolMetrics).values(**values)
        session.exec(  # type: ignore[call-overload]
            stmt.on_conflict_do_update(index_elements=["instrument_id"], set_=values)
        )
        return

    # SQLite (tests): read-modify-write keeps the same semantics.
    existing = session.get(SymbolMetrics, instrument_id) if instrument_id else None
    if existing is None:
        session.add(row)
        return
    for key, value in values.items():
        setattr(existing, key, value)
    session.add(existing)


def metrics_for(session: Session, ticker: str) -> SymbolMetrics | None:
    """The metrics row for a public ticker (keyed by instrument since 4.6b)."""
    return session.exec(
        select(SymbolMetrics).where(col(SymbolMetrics.instrument_id) == instrument_of(ticker))
    ).first()


def set_sentiment(
    session: Session,
    *,
    ticker: str,
    mean_score: float | None,
    article_count: int,
    as_of: date_type | None = None,
) -> None:
    """Write the rolling sentiment aggregate onto a symbol's metrics row.

    Creates the row if the metrics refresh hasn't run yet, so sentiment for a
    newly added symbol isn't lost.
    """
    existing = metrics_for(session, ticker)
    if existing is None:
        existing = SymbolMetrics(ticker=ticker, as_of=as_of)
        session.add(existing)
    existing.sentiment_7d = mean_score
    existing.sentiment_article_count = article_count
    session.add(existing)
