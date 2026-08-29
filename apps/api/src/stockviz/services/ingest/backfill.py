"""One-time backfill of ``price_bars`` from the v1 CSVs.

The CSVs in ``apps/api/seed-data/stock-data-csv-files/`` were produced by
the legacy v1 processor and have the canonical OHLCV shape
(``Date,Open,High,Low,Close,Volume``). We re-use them so the new DB starts
with ~18 years of history per symbol without burning Alpha Vantage quota.
"""

from __future__ import annotations

import csv
import logging
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from sqlmodel import Session, select

from stockviz.models import Symbol
from stockviz.services.ingest.prices import (
    DAILY_INTERVAL,
    BarRecord,
    upsert_bars,
)

logger = logging.getLogger(__name__)

_API_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_CSV_DIR = _API_ROOT / "seed-data" / "stock-data-csv-files"


def _parse_csv(path: Path, ticker: str) -> list[BarRecord]:
    bars: list[BarRecord] = []
    with path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            try:
                bars.append(
                    BarRecord(
                        ticker=ticker,
                        ts=datetime.strptime(row["Date"], "%Y-%m-%d"),
                        interval=DAILY_INTERVAL,
                        open=Decimal(row["Open"]),
                        high=Decimal(row["High"]),
                        low=Decimal(row["Low"]),
                        close=Decimal(row["Close"]),
                        volume=int(float(row["Volume"])),
                        source="v1_csv",
                    )
                )
            except (KeyError, ValueError) as exc:
                logger.warning("backfill: bad row in %s: %s", path.name, exc)
    return bars


def backfill_price_bars_from_csvs(
    session: Session,
    *,
    csv_dir: Path | None = None,
) -> dict[str, int]:
    """Read every ``<TICKER>_processed.csv`` and upsert into ``price_bars``.

    Skips tickers that aren't in the ``symbols`` table (must seed first).
    Returns ``{ticker: rows_written}``.
    """

    src = csv_dir or DEFAULT_CSV_DIR
    if not src.exists():
        logger.warning("backfill: %s not found, nothing to backfill", src)
        return {}

    known = set(session.exec(select(Symbol.ticker)).all())

    written: dict[str, int] = {}
    for path in sorted(src.glob("*_processed.csv")):
        ticker = path.stem.replace("_processed", "")
        if ticker not in known:
            logger.info("backfill: skipping %s — not in symbols table", ticker)
            continue
        bars = _parse_csv(path, ticker)
        if not bars:
            continue
        written[ticker] = upsert_bars(session, bars)
        logger.info("backfill: %s — %d bars from %s", ticker, written[ticker], path.name)
    # upsert_bars stages rows only. This is the high-level CLI/e2e path, so
    # persist the batch; otherwise Session.__exit__ rolls the bars back.
    if written:
        session.commit()
    return written


def ensure_symbols_for_backfill(session: Session, *, csv_dir: Path | None = None) -> int:
    """Add any tickers found on disk that aren't yet in ``symbols``.

    Used when the CSV directory has more tickers than ``companies.json`` (e.g.
    ``ADBE``, ``NFLX`` are present as CSVs but not in the seed). Inserts with
    a stub name = ticker so the row exists for the FK.
    """

    from sqlalchemy.dialects.postgresql import insert as pg_insert

    src = csv_dir or DEFAULT_CSV_DIR
    if not src.exists():
        return 0

    tickers_on_disk = {p.stem.replace("_processed", "") for p in src.glob("*_processed.csv")}
    if not tickers_on_disk:
        return 0

    rows = [{"ticker": t, "name": t} for t in sorted(tickers_on_disk)]
    stmt = pg_insert(Symbol).values(rows).on_conflict_do_nothing(index_elements=["ticker"])
    session.exec(stmt)  # type: ignore[arg-type]
    session.commit()
    return len(rows)
