"""Refresh the precomputed ``symbol_metrics`` rows.

Runs once a day after the price refresh, and has a matching CLI subcommand like
every other scheduled job. Computing these once and reading them back is what
turns the screener from "scan the whole bar table per request" into a single
indexed query.
"""

from __future__ import annotations

import logging
from datetime import date as date_type

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import Session, select

from stockviz._time import utcnow
from stockviz.models import PriceBar, Symbol, SymbolMetrics
from stockviz.services.indicators import compute_rsi

logger = logging.getLogger(__name__)

LOOKBACK_BARS = 260
"""One trading year — enough for RSI(14) and the 52-week range."""

RSI_PERIOD = 14


def compute_for_ticker(session: Session, ticker: str) -> SymbolMetrics | None:
    """Build (but don't persist) the metrics row for one symbol.

    Returns ``None`` when the symbol has no bars at all — there is nothing
    meaningful to store and the screener should not surface it.
    """
    bars = list(
        session.exec(
            select(PriceBar)
            .where(PriceBar.ticker == ticker, PriceBar.interval == "1d")
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

    return SymbolMetrics(
        ticker=ticker,
        as_of=bars[-1].ts.date(),
        last_close=closes[-1],
        rsi_14=rsi,
        high_52w=max(closes),
        low_52w=min(closes),
        computed_at=utcnow(),
    )


def refresh_symbol_metrics(session: Session, *, tickers: list[str] | None = None) -> int:
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
    session.commit()
    logger.info("refresh_symbol_metrics: wrote %d rows", written)
    return written


def _upsert(session: Session, row: SymbolMetrics) -> None:
    """Insert-or-update one metrics row, preserving the sentiment columns."""
    values = {
        "ticker": row.ticker,
        "as_of": row.as_of,
        "last_close": row.last_close,
        "rsi_14": row.rsi_14,
        "high_52w": row.high_52w,
        "low_52w": row.low_52w,
        "computed_at": row.computed_at,
    }

    if session.bind is not None and session.bind.dialect.name == "postgresql":
        stmt = pg_insert(SymbolMetrics).values(**values)
        session.exec(  # type: ignore[call-overload]
            stmt.on_conflict_do_update(index_elements=["ticker"], set_=values)
        )
        return

    # SQLite (tests): read-modify-write keeps the same semantics.
    existing = session.get(SymbolMetrics, row.ticker)
    if existing is None:
        session.add(row)
        return
    for key, value in values.items():
        setattr(existing, key, value)
    session.add(existing)


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
    existing = session.get(SymbolMetrics, ticker)
    if existing is None:
        existing = SymbolMetrics(ticker=ticker, as_of=as_of)
        session.add(existing)
    existing.sentiment_7d = mean_score
    existing.sentiment_article_count = article_count
    session.add(existing)
