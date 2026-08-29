"""Daily OHLCV ingest.

Primary source is yfinance (no key, generous limits). Alpha Vantage is the
fallback when yfinance returns no rows — Alpha Vantage's free tier is 25
requests/day so we don't lean on it.

The two ``fetch_*`` functions take an injectable callable for the actual
network/parsing step so tests pass fixtures instead of mocking ``requests``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import httpx
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import Session

from stockviz.models import PriceBar

logger = logging.getLogger(__name__)

DAILY_INTERVAL = "1d"
SOURCE_YFINANCE = "yfinance"
SOURCE_ALPHA_VANTAGE = "alpha_vantage"

UPSERT_CHUNK_ROWS = 1000
"""Bars per multi-row INSERT.

``price_bars`` binds 9 parameters per row, so Postgres' 65535 parameter cap
allows ~7280. 1000 keeps a wide margin and each statement small enough to stay
responsive.
"""


@dataclass(frozen=True, slots=True)
class BarRecord:
    """One OHLCV bar in the canonical shape used by the upsert layer."""

    ticker: str
    ts: datetime
    interval: str
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    source: str


# ---------------------------------------------------------------------------
# yfinance
# ---------------------------------------------------------------------------


YFinanceHistoryFn = Callable[[str, date | None], Any]
"""(ticker, start_date) -> pandas.DataFrame indexed by date with OHLCV columns."""


def _default_yfinance_history(ticker: str, start: date | None) -> Any:
    # Local import so test fixtures don't have to pay the yfinance import cost.
    import yfinance as yf

    kwargs: dict[str, Any] = {"interval": "1d", "auto_adjust": False, "actions": False}
    if start is None:
        kwargs["period"] = "max"
    else:
        kwargs["start"] = start.isoformat()
    return yf.Ticker(ticker).history(**kwargs)


def fetch_yfinance_daily(
    ticker: str,
    *,
    start: date | None = None,
    history_fn: YFinanceHistoryFn = _default_yfinance_history,
) -> list[BarRecord]:
    """Return daily bars for ``ticker`` from yfinance.

    Returns an empty list if yfinance has nothing — the orchestrator uses that
    as the signal to try Alpha Vantage.
    """

    df = history_fn(ticker, start)
    if df is None or len(df) == 0:
        return []

    bars: list[BarRecord] = []
    for raw_ts, row in df.iterrows():
        ts = raw_ts.to_pydatetime() if hasattr(raw_ts, "to_pydatetime") else raw_ts
        if hasattr(ts, "tzinfo") and ts.tzinfo is not None:
            ts = ts.replace(tzinfo=None)
        try:
            bars.append(
                BarRecord(
                    ticker=ticker,
                    ts=ts,
                    interval=DAILY_INTERVAL,
                    open=Decimal(str(row["Open"])),
                    high=Decimal(str(row["High"])),
                    low=Decimal(str(row["Low"])),
                    close=Decimal(str(row["Close"])),
                    volume=int(row["Volume"]),
                    source=SOURCE_YFINANCE,
                )
            )
        except (KeyError, ValueError, TypeError) as exc:
            logger.warning("yfinance: skipping bad row for %s at %s: %s", ticker, ts, exc)
    return bars


# ---------------------------------------------------------------------------
# Alpha Vantage
# ---------------------------------------------------------------------------


AlphaVantageFetchFn = Callable[[str, str, bool], dict[str, Any]]
"""(ticker, api_key, full) -> raw JSON dict."""


def _default_alpha_vantage_fetch(ticker: str, api_key: str, full: bool) -> dict[str, Any]:
    params = {
        "function": "TIME_SERIES_DAILY",
        "symbol": ticker,
        "outputsize": "full" if full else "compact",
        "datatype": "json",
        "apikey": api_key,
    }
    response = httpx.get("https://www.alphavantage.co/query", params=params, timeout=30.0)
    response.raise_for_status()
    return response.json()


def fetch_alpha_vantage_daily(
    ticker: str,
    *,
    api_key: str,
    full: bool = False,
    fetch_fn: AlphaVantageFetchFn = _default_alpha_vantage_fetch,
) -> list[BarRecord]:
    """Return daily bars for ``ticker`` from Alpha Vantage.

    ``full=True`` requests the entire history (~20 years). The default
    ``compact`` returns the most recent 100 data points, which is enough for
    incremental daily ingest.
    """

    if not api_key:
        return []

    payload = fetch_fn(ticker, api_key, full)
    series = payload.get("Time Series (Daily)")
    if not series:
        # Rate limit / bad symbol — surface for logs but don't raise; the
        # orchestrator decides what to do with empty results.
        note = payload.get("Note") or payload.get("Information") or payload.get("Error Message")
        if note:
            logger.warning("alpha_vantage: %s returned no data: %s", ticker, note)
        return []

    bars: list[BarRecord] = []
    for ts_str, row in series.items():
        try:
            ts = datetime.strptime(ts_str, "%Y-%m-%d")
            bars.append(
                BarRecord(
                    ticker=ticker,
                    ts=ts,
                    interval=DAILY_INTERVAL,
                    open=Decimal(row["1. open"]),
                    high=Decimal(row["2. high"]),
                    low=Decimal(row["3. low"]),
                    close=Decimal(row["4. close"]),
                    volume=int(row["5. volume"]),
                    source=SOURCE_ALPHA_VANTAGE,
                )
            )
        except (KeyError, ValueError) as exc:
            logger.warning("alpha_vantage: skipping bad row for %s at %s: %s", ticker, ts_str, exc)
    bars.sort(key=lambda b: b.ts)
    return bars


# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------


def upsert_bars(session: Session, bars: list[BarRecord]) -> int:
    """Idempotent insert into ``price_bars``.

    Uses Postgres ``ON CONFLICT`` so a re-ingest of the same date refreshes
    the row instead of failing. Returns the number of bars submitted (not the
    number actually changed — Postgres doesn't tell us that cheaply).

    Rows are written in chunks: a full-history yfinance fetch is ~11k bars,
    and one multi-row INSERT of that size blows past Postgres' 65535 bind
    parameter ceiling. See :data:`UPSERT_CHUNK_ROWS`.
    """

    if not bars:
        return 0

    rows = [
        {
            "ticker": b.ticker,
            "ts": b.ts,
            "interval": b.interval,
            "open": b.open,
            "high": b.high,
            "low": b.low,
            "close": b.close,
            "volume": b.volume,
            "source": b.source,
        }
        for b in bars
    ]

    bind = session.get_bind()
    dialect = bind.dialect.name if bind is not None else "sqlite"
    if dialect == "postgresql":
        for start in range(0, len(rows), UPSERT_CHUNK_ROWS):
            chunk = rows[start : start + UPSERT_CHUNK_ROWS]
            stmt = pg_insert(PriceBar).values(chunk)
            stmt = stmt.on_conflict_do_update(
                index_elements=["ticker", "ts", "interval"],
                set_={
                    "open": stmt.excluded.open,
                    "high": stmt.excluded.high,
                    "low": stmt.excluded.low,
                    "close": stmt.excluded.close,
                    "volume": stmt.excluded.volume,
                    "source": stmt.excluded.source,
                },
            )
            session.exec(stmt)  # type: ignore[arg-type]
        return len(rows)

    for row in rows:
        existing = session.get(PriceBar, (row["ticker"], row["ts"], row["interval"]))
        if existing is None:
            session.add(PriceBar(**row))
            continue
        existing.open = row["open"]
        existing.high = row["high"]
        existing.low = row["low"]
        existing.close = row["close"]
        existing.volume = row["volume"]
        existing.source = row["source"]
        session.add(existing)
    return len(rows)


def persist_bars(session: Session, bars: list[BarRecord]) -> int:
    """:func:`upsert_bars` plus commit — CLI / one-off convenience wrapper."""
    written = upsert_bars(session, bars)
    session.commit()
    return written


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def fetch_daily_bars(
    ticker: str,
    *,
    since: date | None = None,
    alpha_vantage_key: str = "",
    history_fn: YFinanceHistoryFn | None = None,
    fetch_fn: AlphaVantageFetchFn | None = None,
) -> list[BarRecord]:
    """Provider I/O only. Does not open a database transaction."""
    kwargs: dict[str, object] = {"start": since}
    if history_fn is not None:
        kwargs["history_fn"] = history_fn
    bars = fetch_yfinance_daily(ticker, **kwargs)  # type: ignore[arg-type]
    if not bars and alpha_vantage_key:
        logger.info("ingest_ticker: %s — yfinance empty, falling back to Alpha Vantage", ticker)
        av_kwargs: dict[str, object] = {"api_key": alpha_vantage_key, "full": since is None}
        if fetch_fn is not None:
            av_kwargs["fetch_fn"] = fetch_fn
        bars = fetch_alpha_vantage_daily(ticker, **av_kwargs)  # type: ignore[arg-type]
    if not bars:
        logger.warning("ingest_ticker: %s — no bars from any source", ticker)
    return bars


def ingest_ticker(
    session: Session,
    ticker: str,
    *,
    since: date | None = None,
    alpha_vantage_key: str = "",
    history_fn: YFinanceHistoryFn | None = None,
    fetch_fn: AlphaVantageFetchFn | None = None,
) -> int:
    """Fetch from yfinance, fall back to Alpha Vantage, write to DB.

    Returns the number of bars written. ``since`` is optional — without it
    yfinance returns the full history (cheap on the free tier). Commits.
    """

    bars = fetch_daily_bars(
        ticker,
        since=since,
        alpha_vantage_key=alpha_vantage_key,
        history_fn=history_fn,
        fetch_fn=fetch_fn,
    )
    if not bars:
        return 0
    return persist_bars(session, bars)
