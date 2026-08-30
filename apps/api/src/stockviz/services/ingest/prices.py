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
from sqlmodel import Session, select

from stockviz.models import PriceBar, QuarantinedPriceBar
from stockviz.services.ingest.bar_semantics import (
    AdjustmentSemantics,
    SessionScope,
    completed_daily_bars,
    new_york_session_date,
    session_label,
)
from stockviz.services.ingest.screening import Disposition, screen_bar

logger = logging.getLogger(__name__)

DAILY_INTERVAL = "1d"
SOURCE_YFINANCE = "yfinance"
SOURCE_ALPHA_VANTAGE = "alpha_vantage"

UPSERT_CHUNK_ROWS = 1000
"""Bars per multi-row INSERT.

``price_bars`` binds 11 parameters per row, so Postgres' 65535 parameter cap
allows ~5957. 1000 keeps a wide margin and each statement small enough to stay
responsive.
"""


def _legacy_integer_volume(value: Decimal) -> int:
    """Bridge canonical Decimal volume to the pre-migration BIGINT column.

    The persisted providers currently emit integral values. Massive remains
    non-persistent, so a fractional value reaching this boundary is rejected
    until evidence determines the replacement NUMERIC scale.
    """

    if not value.is_finite() or value < 0:
        raise ValueError("volume must be a finite non-negative Decimal")
    if value != value.to_integral_value():
        raise ValueError("fractional volume cannot be persisted before the NUMERIC migration")
    return int(value)


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
    volume: Decimal
    source: str
    adjustment_semantics: AdjustmentSemantics
    session_scope: SessionScope


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
        if not isinstance(ts, datetime):
            logger.warning("yfinance: skipping row with non-datetime index for %s: %r", ticker, ts)
            continue
        if ts.tzinfo is not None and ts.utcoffset() is not None:
            ts = session_label(new_york_session_date(ts))
        else:
            ts = session_label(ts.date())
        try:
            open_ = Decimal(str(row["Open"]))
            high = Decimal(str(row["High"]))
            low = Decimal(str(row["Low"]))
            close = Decimal(str(row["Close"]))
            volume = Decimal(str(row["Volume"]))
            if any(not value.is_finite() for value in (open_, high, low, close, volume)):
                raise ValueError("OHLCV values must be finite")
            if any(value < 0 for value in (open_, high, low, close, volume)):
                raise ValueError("OHLCV values must be non-negative")
            if high < max(open_, close, low) or low > min(open_, close, high):
                raise ValueError("malformed OHLC range")
            bars.append(
                BarRecord(
                    ticker=ticker,
                    ts=ts,
                    interval=DAILY_INTERVAL,
                    open=open_,
                    high=high,
                    low=low,
                    close=close,
                    volume=volume,
                    source=SOURCE_YFINANCE,
                    adjustment_semantics=AdjustmentSemantics.SPLIT_ADJUSTED,
                    session_scope=SessionScope.REGULAR,
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
                    volume=Decimal(row["5. volume"]),
                    source=SOURCE_ALPHA_VANTAGE,
                    adjustment_semantics=AdjustmentSemantics.UNADJUSTED,
                    session_scope=SessionScope.REGULAR,
                )
            )
        except (KeyError, ValueError) as exc:
            logger.warning("alpha_vantage: skipping bad row for %s at %s: %s", ticker, ts_str, exc)
    bars.sort(key=lambda b: b.ts)
    return bars


# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------


def _latest_stored_close(
    session: Session, *, ticker: str, interval: str, before: datetime
) -> Decimal | None:
    """Close of the most recent ``price_bars`` row for ``ticker`` strictly
    before ``before``. Used as the trusted prior close for day-over-day
    screening. Best-effort: any failure yields ``None`` (the check is skipped)
    so screening can never break the write path."""

    try:
        stmt = (
            select(PriceBar)
            .where(
                PriceBar.ticker == ticker,
                PriceBar.interval == interval,
                PriceBar.ts < before,
            )
            .order_by(PriceBar.ts.desc())  # type: ignore[attr-defined]
            .limit(1)
        )
        result = session.exec(stmt)
        bar = result.first() if result is not None else None
        return bar.close if bar is not None else None
    except Exception:
        # Screening must never break the write path — a lookup failure just
        # means the day-over-day check is skipped for this bar.
        logger.debug("screening: prior-close lookup failed for %s", ticker, exc_info=True)
        return None


@dataclass(frozen=True, slots=True)
class QuarantinedBar:
    bar: BarRecord
    reason: str
    prev_close: Decimal | None


def screen_bars(
    session: Session, bars: list[BarRecord]
) -> tuple[list[BarRecord], list[QuarantinedBar]]:
    """Split ``bars`` into (accepted, quarantined), dropping rejects with a
    ``WARNING``.

    Bars are walked per ``(ticker, interval)`` in timestamp order. The prior
    close starts from the latest already-stored bar and then follows accepted
    bars in the batch. A quarantined bar does **not** advance the prior close
    — screening fails toward review, so a genuine spike parks the days that
    follow it too until a human releases the first one.
    """

    if not bars:
        return [], []

    accepted: list[BarRecord] = []
    quarantined: list[QuarantinedBar] = []

    ordered = sorted(bars, key=lambda b: (b.ticker, b.interval, b.ts))
    group_start = 0
    while group_start < len(ordered):
        first = ordered[group_start]
        group_end = group_start
        while (
            group_end < len(ordered)
            and ordered[group_end].ticker == first.ticker
            and ordered[group_end].interval == first.interval
        ):
            group_end += 1

        prev_close = _latest_stored_close(
            session, ticker=first.ticker, interval=first.interval, before=first.ts
        )
        for bar in ordered[group_start:group_end]:
            verdict = screen_bar(bar, prev_close)
            if verdict.disposition is Disposition.REJECT:
                logger.warning(
                    "ingest: rejecting bar %s %s %s — %s",
                    bar.ticker,
                    bar.ts.date(),
                    bar.interval,
                    verdict.reason,
                )
                continue
            if verdict.disposition is Disposition.QUARANTINE:
                logger.warning(
                    "ingest: quarantining bar %s %s %s — %s",
                    bar.ticker,
                    bar.ts.date(),
                    bar.interval,
                    verdict.reason,
                )
                quarantined.append(QuarantinedBar(bar, verdict.reason or "", prev_close))
                continue
            accepted.append(bar)
            prev_close = bar.close

        group_start = group_end

    return accepted, quarantined


def record_quarantined_bars(session: Session, quarantined: list[QuarantinedBar]) -> int:
    """Stage one ``price_bar_quarantine`` row per detection. Does not commit."""

    for item in quarantined:
        b = item.bar
        session.add(
            QuarantinedPriceBar(
                ticker=b.ticker,
                ts=b.ts,
                interval=b.interval,
                open=b.open,
                high=b.high,
                low=b.low,
                close=b.close,
                # Diagnostic sink: store volume best-effort rather than raising
                # the way the price_bars boundary does.
                volume=int(b.volume) if b.volume.is_finite() else 0,
                source=b.source,
                adjustment_semantics=b.adjustment_semantics.value,
                session_scope=b.session_scope.value,
                prev_close=item.prev_close,
                reason=item.reason,
            )
        )
    return len(quarantined)


def write_accepted_bars(session: Session, bars: list[BarRecord]) -> int:
    """Idempotent insert of already-screened bars into ``price_bars``.

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
            "volume": _legacy_integer_volume(b.volume),
            "source": b.source,
            "adjustment_semantics": b.adjustment_semantics.value,
            "session_scope": b.session_scope.value,
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
                    "adjustment_semantics": stmt.excluded.adjustment_semantics,
                    "session_scope": stmt.excluded.session_scope,
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
        existing.adjustment_semantics = row["adjustment_semantics"]
        existing.session_scope = row["session_scope"]
        session.add(existing)
    return len(rows)


def upsert_bars(session: Session, bars: list[BarRecord]) -> int:
    """Screen ``bars`` (F-011), then upsert the survivors into ``price_bars``.

    The single choke point for every price-bar write (CLI, backfill, Kafka
    ingest handler). Implausible bars are staged in ``price_bar_quarantine``
    instead; structurally broken bars are dropped with a ``WARNING``. Returns
    the number of rows written to ``price_bars`` — i.e. accepted bars only.
    Does not commit.
    """

    if not bars:
        return 0

    accepted, quarantined = screen_bars(session, bars)
    if quarantined:
        record_quarantined_bars(session, quarantined)
    return write_accepted_bars(session, accepted)


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
    return completed_daily_bars(bars)


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
