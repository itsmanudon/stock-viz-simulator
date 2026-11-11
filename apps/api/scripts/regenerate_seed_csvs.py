"""Rebuild the bundled seed CSVs from yfinance (feature audit MD-1, UI audit T5/T6).

The old v1 CSVs put about 25 years of trading days onto consecutive calendar
days: two rows in seven fell on a weekend, every date but the last few was
wrong, and split jumps (NVDA 10-for-1, AAPL 7-for-1) were left in although
the loader labels the rows split-adjusted.

This script fetches each ticker once, with the same call the nightly ingest
uses (``_default_yfinance_history``: daily, split-adjusted, not dividend
adjusted), keeps the window the seed has always covered, checks the result,
and writes ``<TICKER>_processed.csv`` in the existing format. Run it by hand;
nothing schedules it. The committed CSVs let CI seed offline.

    uv --directory apps/api run python scripts/regenerate_seed_csvs.py
    uv --directory apps/api run python scripts/regenerate_seed_csvs.py --check

``--check`` reads the committed CSVs and runs the checks without any network.
"""

from __future__ import annotations

import argparse
import csv
import math
import sys
import time
from datetime import date
from pathlib import Path

CSV_DIR = Path(__file__).resolve().parents[1] / "seed-data" / "stock-data-csv-files"
START = date(2007, 10, 1)
# Every symbol ends on the same real session, so the seed has one latest
# close. Most of the old files already ended on this date.
END = date(2025, 4, 7)
HEADER = ["Date", "Open", "High", "Low", "Close", "Volume"]
# A day-on-day close ratio beyond this is almost certainly an unadjusted split.
SPLIT_LIKE_RATIO = 1.8


def _fmt(value: float) -> str:
    return f"{round(value, 4):.4f}".rstrip("0").rstrip(".")


def fetch(ticker: str) -> list[list[str]]:
    from stockviz.services.ingest.prices import _default_yfinance_history

    frame = _default_yfinance_history(ticker, START)
    rows: list[list[str]] = []
    for ts, bar in frame.iterrows():
        day = ts.date()
        if day > END:
            continue
        values = [float(bar[name]) for name in ("Open", "High", "Low", "Close")]
        volume = float(bar["Volume"])
        if any(math.isnan(v) or v <= 0 for v in values) or math.isnan(volume):
            continue
        rows.append([day.isoformat(), *(_fmt(v) for v in values), str(int(volume))])
    return rows


def check(rows: list[list[str]]) -> list[str]:
    """Problems that would put a wrong bar on screen. Empty means fine."""
    problems: list[str] = []
    if not rows:
        return ["no rows"]
    days = [date.fromisoformat(r[0]) for r in rows]
    if days != sorted(set(days)):
        problems.append("dates are not strictly increasing")
    weekend = sum(1 for d in days if d.weekday() >= 5)
    if weekend:
        problems.append(f"{weekend} weekend rows")
    if days[-1] != END:
        problems.append(f"ends {days[-1]}, not {END}")
    closes = [float(r[4]) for r in rows]
    for i in range(1, len(closes)):
        ratio = closes[i] / closes[i - 1]
        if ratio > SPLIT_LIKE_RATIO or ratio < 1 / SPLIT_LIKE_RATIO:
            problems.append(f"split-like jump on {days[i]} ({closes[i - 1]} to {closes[i]})")
    for r in rows:
        o, h, lo, c = (float(x) for x in r[1:5])
        if not (lo <= min(o, c) and h >= max(o, c)):
            problems.append(f"high/low do not bound open/close on {r[0]}")
            break
    return problems


def read(path: Path) -> list[list[str]]:
    with path.open(encoding="utf-8", newline="") as fh:
        reader = csv.reader(fh)
        next(reader)
        return list(reader)


def write(path: Path, rows: list[list[str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(HEADER)
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--check", action="store_true", help="check committed CSVs, no network")
    parser.add_argument("tickers", nargs="*", help="default: every CSV in the seed folder")
    args = parser.parse_args()

    tickers = args.tickers or sorted(
        p.name.removesuffix("_processed.csv") for p in CSV_DIR.glob("*_processed.csv")
    )
    failed = 0
    for index, ticker in enumerate(tickers):
        path = CSV_DIR / f"{ticker}_processed.csv"
        if args.check:
            rows = read(path)
        else:
            if index:
                time.sleep(1.5)  # one request per ticker, spaced out
            rows = fetch(ticker)
        problems = check(rows)
        status = "ok" if not problems else "; ".join(problems[:3])
        print(
            f"{ticker:6} {len(rows):5} rows  {rows[0][0] if rows else '-'} .. "
            f"{rows[-1][0] if rows else '-'}  {status}"
        )
        if problems:
            failed += 1
            continue
        if not args.check:
            write(path, rows)
    print(f"{len(tickers) - failed} of {len(tickers)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
