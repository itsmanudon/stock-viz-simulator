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
from datetime import date

from sqlmodel import Session

from stockviz.db import engine
from stockviz.services.ingest.backfill import (
    backfill_price_bars_from_csvs,
    ensure_symbols_for_backfill,
)
from stockviz.services.ingest.dividends import ingest_dividends_for_all
from stockviz.services.ingest.earnings import ingest_earnings_for_all
from stockviz.services.ingest.fx import ingest_fx
from stockviz.services.ingest.metadata import backfill_symbol_metadata
from stockviz.services.ingest.prices import ingest_ticker
from stockviz.services.ingest.seed import seed_symbols
from stockviz.services.metrics import refresh_symbol_metrics
from stockviz.services.recommend import MAX_SCORE, score_universe
from stockviz.services.sentiment.store import backfill_unscored, refresh_symbol_sentiment
from stockviz.services.trading import credit_due_dividends, snapshot_user_navs
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
        session.commit()
    total = sum(written.values())
    print(f"backfilled {total} bars across {len(written)} tickers")
    for ticker, n in sorted(written.items()):
        print(f"  {ticker}: {n}")
    return 0


def _cmd_metadata(args: argparse.Namespace) -> int:
    with Session(engine) as session:
        statuses = backfill_symbol_metadata(session, only=args.tickers or None)
    counts: dict[str, int] = {}
    for status in statuses.values():
        counts[status] = counts.get(status, 0) + 1
    print(f"metadata backfilled: {counts}")
    for ticker, status in sorted(statuses.items()):
        print(f"  {ticker}: {status}")
    return 0


def _cmd_score_sentiment(args: argparse.Namespace) -> int:
    since = date.fromisoformat(args.since) if args.since else None
    with Session(engine) as session:
        written = backfill_unscored(session, since=since, limit=args.limit)
    print(f"scored {written} article(s)")
    return 0


def _cmd_sentiment_aggregate(_args: argparse.Namespace) -> int:
    with Session(engine) as session:
        updated = refresh_symbol_sentiment(session)
    print(f"refreshed rolling sentiment for {updated} symbols")
    return 0


def _cmd_metrics(_args: argparse.Namespace) -> int:
    with Session(engine) as session:
        written = refresh_symbol_metrics(session)
    print(f"refreshed metrics for {written} symbols")
    return 0


def _cmd_recommend(_args: argparse.Namespace) -> int:
    with Session(engine) as session:
        results = score_universe(session, persist=True)
    print(f"scored {len(results)} tickers")
    for r in sorted(results, key=lambda x: x.score, reverse=True):
        flag = "BUY" if r.recommend else "    "
        print(f"  {flag} {r.ticker:6s} score={r.score}/{MAX_SCORE}")
    return 0


def _cmd_dividends(args: argparse.Namespace) -> int:
    with Session(engine) as session:
        results = ingest_dividends_for_all(session, only=args.tickers or None)
    total = sum(results.values())
    print(f"ingested {total} dividend rows across {len(results)} tickers")
    for ticker, n in sorted(results.items()):
        if n:
            print(f"  {ticker}: {n}")
    return 0


def _cmd_earnings(args: argparse.Namespace) -> int:
    """Refresh the provider-backed earnings calendar for active symbols."""
    with Session(engine) as session:
        results = ingest_earnings_for_all(session, only=args.tickers or None)
    total = sum(results.values())
    print(f"ingested {total} earnings rows across {len(results)} tickers")
    for ticker, n in sorted(results.items()):
        if n:
            print(f"  {ticker}: {n}")
    return 0


def _cmd_credit_dividends(_args: argparse.Namespace) -> int:
    from stockviz._time import utcnow

    today = utcnow().date()
    with Session(engine) as session:
        n = credit_due_dividends(session, credit_date=today)
    print(f"credited {n} portfolio(s) for dividends on {today}")
    return 0


def _cmd_snapshot(_args: argparse.Namespace) -> int:
    from stockviz._time import utcnow

    today = utcnow().date()
    with Session(engine) as session:
        n = snapshot_user_navs(session, snapshot_date=today)
    print(f"wrote {n} portfolio snapshots for {today}")
    return 0


def _cmd_settle_options(_args: argparse.Namespace) -> int:
    from stockviz._time import utcnow
    from stockviz.services.options import settle_expired_options

    today = utcnow().date()
    with Session(engine) as session:
        n = settle_expired_options(session, settle_date=today)
    print(f"settled {n} expired option position(s) as of {today}")
    return 0


def _cmd_run_scheduler(_args: argparse.Namespace) -> int:
    from stockviz.workers.scheduler import main as scheduler_main

    return scheduler_main()


def _cmd_publish_outbox(args: argparse.Namespace) -> int:
    from stockviz.workers.outbox_publisher import main as publisher_main

    return publisher_main(["--once"] if args.once else [])


def _cmd_consume_trade_activity(args: argparse.Namespace) -> int:
    from stockviz.workers.trade_activity_consumer import main as consumer_main

    return consumer_main(["--once"] if args.once else [])


def _cmd_consume_market_ingest(args: argparse.Namespace) -> int:
    from stockviz.workers.market_ingest_consumer import main as consumer_main

    return consumer_main(["--once"] if args.once else [])


def _cmd_consume_market_analytics(args: argparse.Namespace) -> int:
    from stockviz.workers.market_analytics_consumer import main as consumer_main

    return consumer_main(["--once"] if args.once else [])


def _cmd_consume_news_ingest(args: argparse.Namespace) -> int:
    from stockviz.workers.news_ingest_consumer import main as consumer_main

    return consumer_main(["--once"] if args.once else [])


def _cmd_consume_news_sentiment(args: argparse.Namespace) -> int:
    from stockviz.workers.news_sentiment_consumer import main as consumer_main

    return consumer_main(["--once"] if args.once else [])


def _cmd_consume_sentiment_aggregate(args: argparse.Namespace) -> int:
    from stockviz.workers.sentiment_aggregate_consumer import main as consumer_main

    return consumer_main(["--once"] if args.once else [])


def _cmd_fx(args: argparse.Namespace) -> int:
    currencies = (
        [c.upper() for c in args.currencies] if args.currencies else _default_fx_currencies()
    )
    total = 0
    for ccy in currencies:
        with Session(engine) as session:
            written = ingest_fx(session, ccy)
        print(f"  {ccy}: {written}")
        total += written
    print(f"ingested {total} FX rates total")
    return 0


def _default_fx_currencies() -> list[str]:
    """Distinct non-USD currencies on active symbols."""
    from sqlmodel import select

    from stockviz.models import Symbol

    with Session(engine) as session:
        rows = list(
            session.exec(
                select(Symbol.currency).where(Symbol.is_active, Symbol.currency != "USD").distinct()
            )
        )
    return [r for r in rows if r]


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

    p_meta = sub.add_parser(
        "metadata", help="Backfill sector/exchange on existing symbols (yfinance)"
    )
    p_meta.add_argument("tickers", nargs="*", help="Optional ticker filter")
    p_meta.set_defaults(fn=_cmd_metadata)

    p_ingest = sub.add_parser("ingest", help="Refresh daily bars for one or more tickers")
    p_ingest.add_argument("tickers", nargs="+")
    p_ingest.set_defaults(fn=_cmd_ingest)

    p_fx = sub.add_parser(
        "fx", help="Refresh daily FX rates (defaults to all non-USD currencies in use)"
    )
    p_fx.add_argument("currencies", nargs="*", help="Optional currency filter, e.g. EUR GBP JPY")
    p_fx.set_defaults(fn=_cmd_fx)

    sub.add_parser(
        "metrics", help="Recompute the screener's precomputed per-symbol metrics"
    ).set_defaults(fn=_cmd_metrics)

    p_sent = sub.add_parser(
        "score-sentiment",
        help="Score news articles that have no result yet for the active model",
    )
    p_sent.add_argument("--since", help="Only score articles published on/after this ISO date")
    p_sent.add_argument("--limit", type=int, help="Maximum articles to score in this run")
    p_sent.set_defaults(fn=_cmd_score_sentiment)

    sub.add_parser(
        "sentiment-aggregate",
        help="Roll per-article sentiment into the per-symbol trailing average",
    ).set_defaults(fn=_cmd_sentiment_aggregate)

    sub.add_parser(
        "recommend", help="Recompute recommendations for every active symbol"
    ).set_defaults(fn=_cmd_recommend)

    sub.add_parser(
        "snapshot-portfolios", help="Upsert today's NAV snapshot for every user"
    ).set_defaults(fn=_cmd_snapshot)

    p_div = sub.add_parser(
        "dividends", help="Backfill dividend history from yfinance for active symbols"
    )
    p_div.add_argument("tickers", nargs="*", help="Optional ticker filter")
    p_div.set_defaults(fn=_cmd_dividends)

    p_earnings = sub.add_parser(
        "earnings", help="Refresh upcoming and recently reported earnings dates from yfinance"
    )
    p_earnings.add_argument("tickers", nargs="*", help="Optional ticker filter")
    p_earnings.set_defaults(fn=_cmd_earnings)

    sub.add_parser(
        "credit-dividends", help="Credit today's due dividends to all eligible portfolios"
    ).set_defaults(fn=_cmd_credit_dividends)

    sub.add_parser(
        "settle-options", help="Settle every option position that has reached expiry"
    ).set_defaults(fn=_cmd_settle_options)

    sub.add_parser(
        "run-scheduler",
        help="Run APScheduler as a dedicated process (Kubernetes singleton)",
    ).set_defaults(fn=_cmd_run_scheduler)

    p_pub = sub.add_parser(
        "publish-outbox",
        help="Publish unpublished outbox events to Kafka (does not run inside the API process)",
    )
    p_pub.add_argument("--once", action="store_true", help="Publish one batch and exit")
    p_pub.set_defaults(fn=_cmd_publish_outbox)

    p_cons = sub.add_parser(
        "consume-trade-activity",
        help="Consume stockviz.trades.v1 into derived portfolio activity",
    )
    p_cons.add_argument("--once", action="store_true", help="Handle at most one message and exit")
    p_cons.set_defaults(fn=_cmd_consume_trade_activity)

    for name, help_text, fn in (
        (
            "consume-market-ingest",
            "Consume stockviz.market.v1 market.refresh.requested",
            _cmd_consume_market_ingest,
        ),
        (
            "consume-market-analytics",
            "Consume stockviz.market.v1 market.bars.refreshed",
            _cmd_consume_market_analytics,
        ),
        (
            "consume-news-ingest",
            "Consume stockviz.news.v1 news.refresh.requested",
            _cmd_consume_news_ingest,
        ),
        (
            "consume-news-sentiment",
            "Consume stockviz.news.v1 news.article.ingested",
            _cmd_consume_news_sentiment,
        ),
        (
            "consume-sentiment-aggregate",
            "Consume stockviz.news.v1 news.sentiment.scored",
            _cmd_consume_sentiment_aggregate,
        ),
    ):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--once", action="store_true", help="Handle at most one message and exit")
        p.set_defaults(fn=fn)

    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
