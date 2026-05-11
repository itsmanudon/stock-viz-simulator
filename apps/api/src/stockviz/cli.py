"""One-off operator commands.

    uv run python -m stockviz.cli seed
    uv run python -m stockviz.cli backfill
    uv run python -m stockviz.cli ingest AAPL [MSFT ...]

Kept argparse-only so we don't add another dep. The scheduler covers the
recurring path; this module is for manual setup and debugging.
"""

from __future__ import annotations

import argparse
import logging
import sys

from sqlmodel import Session

from stockviz.db import engine
from stockviz.services.ingest.backfill import (
    backfill_price_bars_from_csvs,
    ensure_symbols_for_backfill,
)
from stockviz.services.ingest.prices import ingest_ticker
from stockviz.services.ingest.seed import seed_symbols
from stockviz.settings import get_settings

logger = logging.getLogger(__name__)


def _cmd_seed(_args: argparse.Namespace) -> int:
    with Session(engine) as session:
        n = seed_symbols(session)
    print(f"seeded {n} symbols")
    return 0


def _cmd_backfill(_args: argparse.Namespace) -> int:
    with Session(engine) as session:
        ensure_symbols_for_backfill(session)
        written = backfill_price_bars_from_csvs(session)
    total = sum(written.values())
    print(f"backfilled {total} bars across {len(written)} tickers")
    for ticker, n in sorted(written.items()):
        print(f"  {ticker}: {n}")
    return 0


def _cmd_ingest(args: argparse.Namespace) -> int:
    settings = get_settings()
    total = 0
    for ticker in args.tickers:
        with Session(engine) as session:
            written = ingest_ticker(
                session, ticker.upper(), alpha_vantage_key=settings.alpha_vantage_key
            )
        print(f"  {ticker}: {written}")
        total += written
    print(f"ingested {total} bars total")
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    parser = argparse.ArgumentParser(prog="stockviz", description="StockViz API operator commands.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("seed", help="Seed symbols from companies.json").set_defaults(fn=_cmd_seed)
    sub.add_parser(
        "backfill", help="Load v1 CSVs into price_bars (run once after seed)"
    ).set_defaults(fn=_cmd_backfill)

    p_ingest = sub.add_parser("ingest", help="Refresh daily bars for one or more tickers")
    p_ingest.add_argument("tickers", nargs="+")
    p_ingest.set_defaults(fn=_cmd_ingest)

    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
