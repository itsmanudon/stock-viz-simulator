"""Replace the daily bars that yfinance ingest dated a day early.

Until 12 Nov 2026 ``fetch_yfinance_daily`` converted each bar's label
(midnight in the venue's own time zone) to New York before taking the date.
For every venue east of New York that is the previous evening, so each
London, Frankfurt, Tokyo or Mumbai bar was stored one day early: Monday's
session under Sunday, Friday's under Thursday. The rows have the wrong
primary key, so the fixed ingest writes new rows beside them instead of
correcting them.

``redate_ticker`` fixes one ticker: it fetches the history again with the
fixed parser and, in one transaction, deletes the ticker's stored
``yfinance`` daily bars and quarantine rows and writes the new ones. Rows
from any other source (the Zerodha ``bulk_*`` imports, the v1 CSVs) are
left alone. If yfinance returns nothing the ticker is skipped, so a failed
fetch never leaves a ticker without its history. Running it twice is
harmless: the second run replaces correct rows with the same rows.

Affected tickers are chosen by venue (``VENUE_BY_SUFFIX``): a ticker
without a suffix counts as New York. A crypto or FX ticker, which yfinance
labels in UTC or London time, would need naming explicitly; production holds
none (checked 12 Nov 2026).

Metrics, signals and recommendations are recomputed from ``price_bars`` by
the nightly jobs, so they correct themselves on the next run.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, time

from sqlalchemy import ColumnElement, delete, func
from sqlmodel import Session, col, select

from stockviz.models import PriceBar, QuarantinedPriceBar
from stockviz.services.ingest.bar_semantics import NEW_YORK
from stockviz.services.ingest.prices import (
    DAILY_INTERVAL,
    SOURCE_YFINANCE,
    YFinanceHistoryFn,
    fetch_daily_bars,
    upsert_bars,
)
from stockviz.services.markets.calendar import venue_for_ticker, venue_zone

# One winter and one summer date: a venue is affected if its midnight is the
# previous day in New York in either half of the year.
_PROBE_DATES = (date(2026, 1, 15), date(2026, 7, 15))


def was_misdated(ticker: str) -> bool:
    """Whether the old New York conversion moved this ticker's bars a day."""

    zone = venue_zone(venue_for_ticker(ticker))
    return any(
        datetime.combine(day, time.min, tzinfo=zone).astimezone(NEW_YORK).date() != day
        for day in _PROBE_DATES
    )


@dataclass(frozen=True)
class RedateResult:
    ticker: str
    deleted_bars: int
    deleted_quarantine: int
    written: int
    skipped: bool = False


def _yfinance_daily(
    model: type[PriceBar] | type[QuarantinedPriceBar], ticker: str
) -> tuple[ColumnElement[bool], ...]:
    return (
        col(model.ticker) == ticker,
        col(model.interval) == DAILY_INTERVAL,
        col(model.source) == SOURCE_YFINANCE,
    )


def count_stored(session: Session, ticker: str) -> tuple[int, int]:
    """(price_bars, price_bar_quarantine) yfinance daily rows held for ``ticker``."""

    bars = session.exec(
        select(func.count()).select_from(PriceBar).where(*_yfinance_daily(PriceBar, ticker))
    ).one()
    quarantine = session.exec(
        select(func.count())
        .select_from(QuarantinedPriceBar)
        .where(*_yfinance_daily(QuarantinedPriceBar, ticker))
    ).one()
    return int(bars), int(quarantine)


def misdated_tickers(session: Session) -> list[str]:
    """Tickers holding yfinance daily bars on a venue east of New York."""

    held = session.exec(
        select(PriceBar.ticker)
        .where(
            col(PriceBar.interval) == DAILY_INTERVAL,
            col(PriceBar.source) == SOURCE_YFINANCE,
        )
        .distinct()
    ).all()
    return sorted(t for t in held if was_misdated(t))


def redate_ticker(
    session: Session,
    ticker: str,
    *,
    history_fn: YFinanceHistoryFn | None = None,
    now: datetime | None = None,
) -> RedateResult:
    """Fetch ``ticker`` again and swap its yfinance daily rows. Commits."""

    # No Alpha Vantage key: only yfinance rows are being replaced, and the
    # fallback's 25-a-day quota is not spent on a repair.
    bars = fetch_daily_bars(ticker, history_fn=history_fn, now=now)
    bars = [b for b in bars if b.source == SOURCE_YFINANCE]
    if not bars:
        return RedateResult(ticker, 0, 0, 0, skipped=True)

    deleted_bars = session.exec(  # type: ignore[call-overload]
        delete(PriceBar).where(*_yfinance_daily(PriceBar, ticker))
    ).rowcount
    deleted_quarantine = session.exec(  # type: ignore[call-overload]
        delete(QuarantinedPriceBar).where(*_yfinance_daily(QuarantinedPriceBar, ticker))
    ).rowcount
    written = upsert_bars(session, bars)
    session.commit()
    return RedateResult(ticker, deleted_bars, deleted_quarantine, written)


def redate_tickers(
    session: Session,
    tickers: Iterable[str],
    *,
    history_fn: YFinanceHistoryFn | None = None,
    now: datetime | None = None,
) -> list[RedateResult]:
    return [redate_ticker(session, t, history_fn=history_fn, now=now) for t in tickers]
