"""Backfill of ``price_bars`` from the bundled seed CSVs.

The CSVs in ``apps/api/seed-data/stock-data-csv-files/`` hold daily,
split-adjusted bars on real trading dates (``Date,Open,High,Low,Close,Volume``),
rebuilt from yfinance by ``scripts/regenerate_seed_csvs.py``. They let a new
database, and CI, start with ~17 years of history per symbol offline.

The v1 files they replaced put trading days on consecutive calendar days and
left splits in (feature audit MD-1). A database loaded from those keeps the
wrong rows after a plain re-run, because upsert never deletes: use
``replace=True`` (``stockviz.cli backfill --replace``) to drop a ticker's
``v1_csv`` bars before loading its file.
"""

from __future__ import annotations

import csv
import logging
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from sqlmodel import Session, col, delete, select

from stockviz.models import PriceBar, Symbol
from stockviz.services.ingest.bar_semantics import AdjustmentSemantics, SessionScope
from stockviz.services.ingest.prices import (
    DAILY_INTERVAL,
    BarRecord,
    upsert_bars,
)
from stockviz.services.instruments import instrument_of

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
                        volume=Decimal(row["Volume"]),
                        source="v1_csv",
                        adjustment_semantics=AdjustmentSemantics.SPLIT_ADJUSTED,
                        session_scope=SessionScope.REGULAR,
                    )
                )
            except (KeyError, ValueError) as exc:
                logger.warning("backfill: bad row in %s: %s", path.name, exc)
    return bars


def backfill_price_bars_from_csvs(
    session: Session,
    *,
    csv_dir: Path | None = None,
    replace: bool = False,
) -> dict[str, int]:
    """Read every ``<TICKER>_processed.csv`` and upsert into ``price_bars``.

    Skips tickers that aren't in the ``symbols`` table (must seed first).
    With ``replace``, first deletes that ticker's daily bars whose source is
    ``v1_csv``; bars from live ingest are never touched. Returns
    ``{ticker: rows_written}``.
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
        if replace:
            session.exec(
                delete(PriceBar).where(
                    col(PriceBar.instrument_id) == instrument_of(ticker),
                    col(PriceBar.interval) == DAILY_INTERVAL,
                    col(PriceBar.source) == "v1_csv",
                )
            )  # type: ignore[call-overload]
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
