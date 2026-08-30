"""Resample the added `data/` bulk history to daily bars and load `price_bars`.

Sources (only what the app actually reads — daily `1d` bars):

  data/1hr-10-years-data/<NAME>_1hr_bulk_data.csv   -> <NAME>.NS   (INR, NSE)
  data/2025-USD-commodities/<SYM>_USD_M1_*.csv      -> <SYM>       (USD, COMMODITY)

Each intraday file is grouped by its local calendar date into one OHLCV bar
(open = first, high = max, low = min, close = last, volume = sum) and written
through the real `upsert_bars`, so F-011 plausibility screening still applies.

A linearly interpolated USD/INR `fx_rates` series is written over the loaded
date range so INR positions convert to USD cash (the ledger is USD-only).

Run from the repo root:

    uv --directory apps/api run python scripts/seed_bulk_daily.py --commit
    uv --directory apps/api run python scripts/seed_bulk_daily.py --data-dir /path/to/data --commit

Without --commit it parses and screens everything but rolls back (dry run).
"""

from __future__ import annotations

import argparse
import csv
import logging
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import Session

from stockviz.db import engine
from stockviz.models import FxRate, Symbol
from stockviz.services.ingest.bar_semantics import AdjustmentSemantics, SessionScope, session_label
from stockviz.services.ingest.prices import DAILY_INTERVAL, BarRecord, upsert_bars

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
# stockviz.db builds the engine with echo=True; that is far too noisy for a
# bulk load, so quiet the statement log back down to warnings here.
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
log = logging.getLogger("seed_bulk_daily")

REPO_ROOT = Path(__file__).resolve().parents[3]

# USD per 1 INR, anchored at the ends of the loaded history (≈ ₹62/$ in 2015,
# ≈ ₹86/$ in 2026) and linearly interpolated between. Rough but monotonic, which
# keeps historical backtests from seeing a flat or absurd FX curve.
INR_USD_2015 = Decimal("0.01613")
INR_USD_2026 = Decimal("0.01163")
FX_ANCHOR_START = date(2015, 1, 1)
FX_ANCHOR_END = date(2026, 6, 30)


def _daily_from_intraday(
    rows: list[tuple[date, Decimal, Decimal, Decimal, Decimal, int]],
) -> list[tuple[date, Decimal, Decimal, Decimal, Decimal, int]]:
    """Collapse (date, o, h, lo, c, v) intraday rows into one bar per date."""
    buckets: dict[date, list[tuple[Decimal, Decimal, Decimal, Decimal, int]]] = defaultdict(list)
    for d, o, h, lo, c, v in rows:
        buckets[d].append((o, h, lo, c, v))
    out = []
    for d in sorted(buckets):
        bars = buckets[d]
        out.append(
            (
                d,
                bars[0][0],
                max(b[1] for b in bars),
                min(b[2] for b in bars),
                bars[-1][3],
                sum(b[4] for b in bars),
            )
        )
    return out


def _bar_records(
    ticker: str,
    daily: list[tuple[date, Decimal, Decimal, Decimal, Decimal, int]],
    *,
    source: str,
) -> list[BarRecord]:
    return [
        BarRecord(
            ticker=ticker,
            ts=session_label(d),
            interval=DAILY_INTERVAL,
            open=o,
            high=h,
            low=lo,
            close=c,
            volume=Decimal(v),
            source=source,
            adjustment_semantics=AdjustmentSemantics.UNADJUSTED,
            session_scope=SessionScope.REGULAR,
        )
        for d, o, h, lo, c, v in daily
    ]


def _read_nse_hourly(path: Path) -> list[tuple[date, Decimal, Decimal, Decimal, Decimal, int]]:
    """`date,open,high,low,close,volume` with tz-aware `date` (IST)."""
    rows = []
    with path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for r in reader:
            try:
                ts = datetime.fromisoformat(r["date"])
                rows.append(
                    (
                        ts.date(),
                        Decimal(r["open"]),
                        Decimal(r["high"]),
                        Decimal(r["low"]),
                        Decimal(r["close"]),
                        int(float(r["volume"] or 0)),
                    )
                )
            except (KeyError, ValueError, InvalidOperation) as exc:
                log.debug("skip row in %s: %s", path.name, exc)
    return rows


def _read_mt_minute(path: Path) -> list[tuple[date, Decimal, Decimal, Decimal, Decimal, int]]:
    """MetaTrader export: tab-separated `<DATE>\\t<TIME>\\t<OPEN>...<TICKVOL>...`."""
    rows = []
    with path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        for r in reader:
            try:
                d = datetime.strptime(r["<DATE>"].strip(), "%Y.%m.%d").date()
                rows.append(
                    (
                        d,
                        Decimal(r["<OPEN>"]),
                        Decimal(r["<HIGH>"]),
                        Decimal(r["<LOW>"]),
                        Decimal(r["<CLOSE>"]),
                        int(float(r.get("<TICKVOL>") or 0)),
                    )
                )
            except (KeyError, ValueError, InvalidOperation) as exc:
                log.debug("skip row in %s: %s", path.name, exc)
    return rows


def _upsert_symbol(session: Session, ticker: str, name: str, currency: str, exchange: str) -> None:
    stmt = (
        pg_insert(Symbol)
        .values(ticker=ticker, name=name, currency=currency, exchange=exchange)
        .on_conflict_do_nothing(index_elements=["ticker"])
    )
    session.exec(stmt)  # type: ignore[arg-type]


def _write_fx_inr(session: Session, dates: set[date]) -> int:
    span = (FX_ANCHOR_END - FX_ANCHOR_START).days or 1
    rows = []
    for d in sorted(dates):
        frac = Decimal((d - FX_ANCHOR_START).days) / Decimal(span)
        frac = min(max(frac, Decimal(0)), Decimal(1))
        rate = INR_USD_2015 + (INR_USD_2026 - INR_USD_2015) * frac
        rows.append({"currency": "INR", "date": d, "usd_rate": rate, "source": "seed_bulk_interp"})
    if not rows:
        return 0
    for i in range(0, len(rows), 1000):
        chunk = rows[i : i + 1000]
        stmt = pg_insert(FxRate).values(chunk)
        stmt = stmt.on_conflict_do_update(
            index_elements=["currency", "date"],
            set_={"usd_rate": stmt.excluded.usd_rate, "source": stmt.excluded.source},
        )
        session.exec(stmt)  # type: ignore[arg-type]
    return len(rows)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", type=Path, default=REPO_ROOT / "data")
    ap.add_argument("--commit", action="store_true", help="persist (default: dry run + rollback)")
    args = ap.parse_args()

    # (dir, filename glob, filename-suffix to strip, resample source tag).
    # The 1-minute set is loaded *after* the hourly one so its finer highs/lows
    # win on the ~3 years they overlap, and it extends the series to its later
    # last session.
    nse_sources = [
        (
            args.data_dir / "1hr-10-years-data",
            "*_1hr_bulk_data.csv",
            "_1hr_bulk_data.csv",
            "bulk_1hr_resampled",
        ),
        (
            args.data_dir / "1-min-3-years-data",
            "*_bulk_data.csv",
            "_bulk_data.csv",
            "bulk_1min_resampled",
        ),
    ]
    cmdty_dir = args.data_dir / "2025-USD-commodities"
    if not nse_sources[0][0].exists():
        log.error("not found: %s", nse_sources[0][0])
        return 1

    inr_dates: set[date] = set()
    total_syms = total_bars = 0
    seen_tickers: set[str] = set()

    with Session(engine) as session:
        for src_dir, glob_pat, suffix, tag in nse_sources:
            if not src_dir.exists():
                continue
            for path in sorted(src_dir.glob(glob_pat)):
                name = path.name.replace(suffix, "")
                ticker = f"{name}.NS"
                daily = _daily_from_intraday(_read_nse_hourly(path))
                if not daily:
                    log.warning("%s: no rows", path.name)
                    continue
                _upsert_symbol(session, ticker, name, "INR", "NSE")
                bars = _bar_records(ticker, daily, source=tag)
                written = upsert_bars(session, bars)
                inr_dates.update(d for d, *_ in daily)
                total_bars += written
                if ticker not in seen_tickers:
                    seen_tickers.add(ticker)
                    total_syms += 1
                log.info(
                    "%-16s %5d daily bars  %s..%s  (%s)",
                    ticker,
                    written,
                    daily[0][0],
                    daily[-1][0],
                    tag,
                )

        if cmdty_dir.exists():
            for path in sorted(cmdty_dir.glob("*.csv")):
                sym = path.name.split("_")[0]  # GOLD / SILVER / US-OIL
                daily = _daily_from_intraday(_read_mt_minute(path))
                if not daily:
                    continue
                _upsert_symbol(session, sym, f"{sym} (USD spot)", "USD", "COMMODITY")
                bars = _bar_records(sym, daily, source="bulk_mt_resampled")
                written = upsert_bars(session, bars)
                total_syms += 1
                total_bars += written
                log.info("%-16s %5d daily bars  %s..%s", sym, written, daily[0][0], daily[-1][0])

        fx = _write_fx_inr(session, inr_dates)
        log.info("USD/INR fx_rates rows: %d", fx)

        if args.commit:
            session.commit()
            log.info("committed: %d symbols, %d daily bars, %d fx rows", total_syms, total_bars, fx)
        else:
            session.rollback()
            log.info(
                "DRY RUN (rolled back): would load %d symbols, %d bars", total_syms, total_bars
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
