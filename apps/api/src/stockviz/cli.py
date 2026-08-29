"""One-off operator commands.

    uv run python -m stockviz.cli seed
    uv run python -m stockviz.cli backfill
    uv run python -m stockviz.cli ingest AAPL [MSFT ...]
    uv run python -m stockviz.cli news AAPL [MSFT ...]

Kept argparse-only so we don't add another dep. The scheduler covers the
recurring path; this module is for manual setup and debugging.
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections import Counter
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo

from sqlmodel import Session

from stockviz.db import engine
from stockviz.services.ingest.backfill import (
    backfill_price_bars_from_csvs,
    ensure_symbols_for_backfill,
)
from stockviz.services.ingest.bar_semantics import (
    AdjustmentSemantics,
    SessionScope,
    completed_daily_bars,
)
from stockviz.services.ingest.dividends import ingest_dividends_for_all
from stockviz.services.ingest.earnings import ingest_earnings_for_all
from stockviz.services.ingest.fx import ingest_fx
from stockviz.services.ingest.metadata import backfill_symbol_metadata
from stockviz.services.ingest.prices import BarRecord, fetch_yfinance_daily, ingest_ticker
from stockviz.services.ingest.providers.massive import (
    MASSIVE_API_ROOT,
    MassiveProviderError,
    MassiveSemanticError,
    fetch_massive_daily,
    fetch_massive_dividends,
    fetch_massive_minutes,
    fetch_massive_open_close,
    fetch_massive_splits,
    reconstruct_massive_session,
)
from stockviz.services.ingest.seed import seed_symbols
from stockviz.services.ingest.semantic_acceptance import (
    SessionScopeEvidence,
    audit_decimal_boundaries,
    build_session_evidence,
    recommend_decimal_storage,
    select_session_samples,
    technical_recommendation,
)
from stockviz.services.ingest.shadow import (
    ActionWindow,
    RawLatestSessions,
    SymbolComparison,
    audit_volume_precision,
    compare_symbol,
)
from stockviz.services.ingest.shadow_report import ShadowRun, write_shadow_report
from stockviz.services.metrics import refresh_symbol_metrics
from stockviz.services.recommend import MAX_SCORE, score_universe
from stockviz.services.sentiment.store import backfill_unscored, refresh_symbol_sentiment
from stockviz.services.trading import credit_due_dividends, snapshot_user_navs
from stockviz.settings import get_settings

logger = logging.getLogger(__name__)

DEFAULT_SHADOW_SYMBOLS = ["AAPL", "MSFT", "NVDA", "AMZN", "META", "TSLA", "JPM"]
VOLUME_PRECISION_PROBES = ["C", "GE", "AIG"]
DEFAULT_SHADOW_OUTPUT = Path("artifacts/private/massive-shadow")


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


def _cmd_news(args: argparse.Namespace) -> int:
    """Manual twin of the news-ingest Kafka consumer.

    Builds the same ``news.refresh.requested`` envelope the scheduler enqueues
    and hands it to the consumer's own ``process_payload``. Provider I/O,
    de-duplication, the ``news.article.ingested`` outbox rows and the inbox
    receipt are therefore the worker's code, not a second copy of it — the only
    thing this skips is the trip through Kafka.
    """
    from sqlmodel import select

    from stockviz.events.outbox import build_news_refresh_requested
    from stockviz.models import Symbol
    from stockviz.scheduler import company_name_map
    from stockviz.workers.news_ingest_consumer import process_payload

    settings = get_settings()
    if not settings.newsdata_key:
        print(
            "news: NEWSDATA_KEY is not set — the provider cannot be called, so "
            "this would silently ingest nothing. Refusing to run.",
            file=sys.stderr,
        )
        return 2

    if args.tickers:
        tickers = [t.strip().upper() for t in args.tickers]
    else:
        with Session(engine) as session:
            tickers = list(session.exec(select(Symbol.ticker).where(Symbol.is_active)).all())
    if not tickers:
        print("news: no tickers to refresh")
        return 0

    names = company_name_map()
    total = 0
    for ticker in tickers:
        query = names.get(ticker, ticker)
        envelope = build_news_refresh_requested(
            ticker=ticker,
            company_name=query,
            reason="manual",
        )
        before = _news_article_count(ticker)
        result = process_payload(envelope.model_dump(mode="json"))
        inserted = _news_article_count(ticker) - before
        total += inserted
        print(f"  {ticker}: {inserted} new ({result}, query={query!r})")
    print(f"ingested {total} new article(s) across {len(tickers)} ticker(s)")
    return 0


def _news_article_count(ticker: str) -> int:
    from sqlalchemy import func
    from sqlmodel import select

    from stockviz.models import NewsArticle

    with Session(engine) as session:
        return int(
            session.exec(
                select(func.count()).select_from(NewsArticle).where(NewsArticle.ticker == ticker)
            ).one()
        )


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


def _open_close_bar(
    ticker: str,
    session_date: date,
    value: object,
) -> BarRecord:
    return BarRecord(
        ticker=ticker,
        ts=datetime.combine(session_date, datetime.min.time()),
        interval="1d",
        open=value.open,  # type: ignore[attr-defined]
        high=value.high,  # type: ignore[attr-defined]
        low=value.low,  # type: ignore[attr-defined]
        close=value.close,  # type: ignore[attr-defined]
        volume=value.volume,  # type: ignore[attr-defined]
        source="massive_open_close",
        adjustment_semantics=AdjustmentSemantics.SPLIT_ADJUSTED,
        session_scope=SessionScope.REGULAR,
    )


def _rendered_request_specs(
    ticker: str,
    *,
    start: date,
    end: date,
) -> list[dict[str, object]]:
    symbol = quote(ticker, safe=".")
    common = {"sort": "asc", "limit": "1000"}
    return [
        {
            "purpose": "adjusted_daily_aggregates",
            "endpoint": (
                f"{MASSIVE_API_ROOT}/v2/aggs/ticker/{symbol}/range/1/day/"
                f"{start.isoformat()}/{end.isoformat()}"
            ),
            "params": {"adjusted": "true", "sort": "asc", "limit": "50000"},
            "date_range": {"from": start.isoformat(), "to": end.isoformat()},
        },
        {
            "purpose": "splits",
            "endpoint": f"{MASSIVE_API_ROOT}/stocks/v1/splits",
            "params": {
                "ticker": ticker,
                "execution_date.gte": start.isoformat(),
                "execution_date.lte": end.isoformat(),
                **common,
            },
            "date_range": {"from": start.isoformat(), "to": end.isoformat()},
        },
        {
            "purpose": "dividends",
            "endpoint": f"{MASSIVE_API_ROOT}/stocks/v1/dividends",
            "params": {
                "ticker": ticker,
                "ex_dividend_date.gte": start.isoformat(),
                "ex_dividend_date.lte": end.isoformat(),
                **common,
            },
            "date_range": {"from": start.isoformat(), "to": end.isoformat()},
        },
    ]


def _historical_blockers(comparisons: dict[str, SymbolComparison]) -> list[str]:
    blockers: list[str] = []
    for result in comparisons.values():
        if result.common_sessions == 0:
            blockers.append(f"{result.ticker}: no common completed sessions")
        if result.reference_only_sessions or result.candidate_only_sessions:
            blockers.append(f"{result.ticker}: missing or extra provider sessions")
        if any(stats.over_10_bps for stats in result.fields.values()):
            blockers.append(f"{result.ticker}: OHLC mismatch exceeds 10 bps")
        if result.volume.over_1_percent:
            blockers.append(f"{result.ticker}: volume mismatch exceeds 1 percent")
    return blockers


def run_market_shadow(
    *,
    symbols: list[str],
    start: date,
    end: date,
    api_key: str,
    precision_symbols: list[str] | None = None,
) -> ShadowRun:
    """Run a private, in-memory yfinance/Massive comparison without a DB session."""

    comparisons: dict[str, SymbolComparison] = {}
    candidate_bars_for_precision: list[BarRecord] = []
    scope_evidence: list[SessionScopeEvidence] = []
    request_evidence: list[dict[str, object]] = []
    for ticker in symbols:
        request_evidence.extend(_rendered_request_specs(ticker, start=start, end=end))
        reference_raw = [
            bar
            for bar in fetch_yfinance_daily(ticker, start=start)
            if start <= bar.ts.date() <= end
        ]
        candidate_raw = fetch_massive_daily(
            ticker,
            start=start,
            end=end,
            api_key=api_key,
        )
        candidate_bars_for_precision.extend(candidate_raw)
        provider_actions = [
            *fetch_massive_splits(ticker, start=start, end=end, api_key=api_key),
            *fetch_massive_dividends(ticker, start=start, end=end, api_key=api_key),
        ]
        actions = [
            ActionWindow(kind=action.kind, effective_date=action.effective_date)
            for action in provider_actions
        ]
        reference_completed = completed_daily_bars(reference_raw)
        candidate_completed = completed_daily_bars(candidate_raw)
        raw_latest = RawLatestSessions(
            reference=max((bar.ts.date() for bar in reference_raw), default=None),
            candidate=max((bar.ts.date() for bar in candidate_raw), default=None),
        )
        result = compare_symbol(
            reference_completed,
            candidate_completed,
            actions=actions,
            raw_latest=raw_latest,
        )
        comparisons[ticker] = result

        reference_by_date = {bar.ts.date(): bar for bar in reference_completed}
        reference_dates = set(reference_by_date)
        candidate_by_date = {bar.ts.date(): bar for bar in candidate_completed}
        common_dates = sorted(reference_dates & set(candidate_by_date))
        for selection in select_session_samples(common_dates, actions):
            session_date = selection.session_date
            open_close_endpoint = (
                f"{MASSIVE_API_ROOT}/v1/open-close/{quote(ticker, safe='.')}/"
                f"{session_date.isoformat()}"
            )
            open_close_request: dict[str, object] = {
                "purpose": "adjusted_daily_open_close",
                "endpoint": open_close_endpoint,
                "params": {"adjusted": "true"},
                "date_range": {
                    "from": session_date.isoformat(),
                    "to": session_date.isoformat(),
                },
            }
            try:
                open_close_value = fetch_massive_open_close(
                    ticker,
                    session_date=session_date,
                    api_key=api_key,
                )
                open_close_bar = _open_close_bar(ticker, session_date, open_close_value)
                open_close_request["status"] = "complete"
            except (MassiveProviderError, MassiveSemanticError):
                open_close_bar = None
                open_close_request["status"] = "unavailable_or_invalid"
            request_evidence.append(open_close_request)

            minute_endpoint = (
                f"{MASSIVE_API_ROOT}/v2/aggs/ticker/{quote(ticker, safe='.')}/range/"
                f"1/minute/{session_date.isoformat()}/{session_date.isoformat()}"
            )
            fallback_minute_request: dict[str, object] = {
                "purpose": "adjusted_one_minute_aggregates",
                "endpoint": minute_endpoint,
                "params": {"adjusted": "true", "sort": "asc", "limit": "50000"},
                "requested_start": session_date.isoformat(),
                "requested_end": session_date.isoformat(),
                "pagination_complete": False,
            }
            try:
                minute_series = fetch_massive_minutes(
                    ticker,
                    session_date=session_date,
                    api_key=api_key,
                )
                reconstructed = reconstruct_massive_session(minute_series)
                minute_request = reconstructed.request.as_dict()
                retrieval_status = reconstructed.retrieval_status
                regular_bar = reconstructed.regular
                all_session_bar = reconstructed.all_session
                expected_minutes = reconstructed.expected_regular_minutes
                observed_minutes = reconstructed.observed_regular_minutes
                absence_counts = Counter(gap.reason for gap in reconstructed.gaps)
                if retrieval_status != "complete":
                    absence_counts[retrieval_status] = expected_minutes
                for value in (regular_bar, all_session_bar):
                    if value is not None:
                        candidate_bars_for_precision.append(value)
            except (MassiveProviderError, MassiveSemanticError):
                minute_request = fallback_minute_request
                retrieval_status = "retrieval_or_pagination_gap"
                regular_bar = None
                all_session_bar = None
                expected_minutes = 390
                observed_minutes = 0
                absence_counts = Counter({"retrieval_or_pagination_gap": 390})
            request_evidence.append(dict(minute_request))
            scope_evidence.append(
                build_session_evidence(
                    selection=selection,
                    daily=candidate_by_date[session_date],
                    intraday_regular=regular_bar,
                    intraday_all_session=all_session_bar,
                    open_close=open_close_bar,
                    yfinance=reference_by_date[session_date],
                    retrieval_status=retrieval_status,
                    expected_regular_minutes=expected_minutes,
                    observed_regular_minutes=observed_minutes,
                    absence_reason_counts=absence_counts,
                    request={"minute": minute_request, "open_close": open_close_request},
                )
            )

    comparison_symbols = set(symbols)
    for ticker in precision_symbols if precision_symbols is not None else VOLUME_PRECISION_PROBES:
        if ticker in comparison_symbols:
            continue
        candidate_bars_for_precision.extend(
            fetch_massive_daily(ticker, start=start, end=end, api_key=api_key)
        )

    precision_audit = audit_volume_precision(candidate_bars_for_precision)
    recommendation = technical_recommendation(comparisons, scope_evidence)
    blockers = _historical_blockers(comparisons)
    blockers.extend(
        f"{sample.ticker} {sample.selection.session_date}: {sample.classification}"
        for sample in scope_evidence
        if sample.classification != "regular_session_consistent"
    )
    if not scope_evidence:
        blockers.append("no minute-level session-scope samples completed")
    return ShadowRun(
        started_at=datetime.now(UTC),
        requested_start=start,
        requested_end=end,
        symbols=comparisons,
        volume_precision=precision_audit,
        session_scope_evidence=scope_evidence,
        decimal_boundaries=audit_decimal_boundaries(),
        decimal_storage_recommendation=recommend_decimal_storage(precision_audit),
        reproducibility={
            "historical_date_range": {"from": start.isoformat(), "to": end.isoformat()},
            "symbols": list(symbols),
            "precision_probe_symbols": list(
                precision_symbols if precision_symbols is not None else VOLUME_PRECISION_PROBES
            ),
            "timezone": "America/New_York",
            "timestamp_assumption": (
                "Massive t is UTC epoch milliseconds converted exactly once to America/New_York"
            ),
            "regular_session": "09:30 inclusive to 16:00 exclusive",
            "sampling_rule": (
                "oldest/middle/newest non-action common sessions plus previous/on/next "
                "common sessions around the latest split and latest dividend per symbol"
            ),
            "adjustment_flags": {
                "daily_aggregates": True,
                "minute_aggregates": True,
                "open_close": True,
                "yfinance_auto_adjust": False,
            },
            "endpoint_requests": request_evidence,
            "http_retry_policy": {
                "statuses": [429, 503, 504],
                "maximum_attempts": 7,
                "retry_after_seconds_ceiling": 30,
                "fallback_backoff_seconds": [1, 2, 4, 8, 16, 30],
            },
            "arithmetic": "exact Decimal only; no float coercion, truncation, or rounding",
        },
        blockers=blockers,
        technical_recommendation=recommendation,
        licensing_gate="not_approved_individual_subscription",
        verification={
            "unit_tests": "not run by market-shadow command",
            "clean_container": "run credential-free workflow separately",
        },
    )


def _five_years_before(value: date) -> date:
    try:
        return value.replace(year=value.year - 5)
    except ValueError:
        return value.replace(year=value.year - 5, day=28)


def _cmd_market_shadow(args: argparse.Namespace) -> int:
    settings = get_settings()
    if not settings.massive_api_key.strip():
        print(
            "market-shadow: MASSIVE_API_KEY is required for private shadow execution.",
            file=sys.stderr,
        )
        return 2
    try:
        start = date.fromisoformat(args.from_date)
        end = date.fromisoformat(args.to_date)
    except ValueError:
        print("market-shadow: date range values must use YYYY-MM-DD.", file=sys.stderr)
        return 2
    if start > end:
        print("market-shadow: date range start must be on or before end.", file=sys.stderr)
        return 2
    symbols = list(
        dict.fromkeys(ticker.strip().upper() for ticker in args.tickers if ticker.strip())
    )
    if not symbols:
        symbols = list(DEFAULT_SHADOW_SYMBOLS)
    try:
        run = run_market_shadow(
            symbols=symbols,
            start=start,
            end=end,
            api_key=settings.massive_api_key,
        )
    except MassiveProviderError as exc:
        print(f"market-shadow: provider execution failed: {exc}", file=sys.stderr)
        return 1
    json_path, markdown_path = write_shadow_report(run, Path(args.output_dir))
    print(f"private JSON report: {json_path}")
    print(f"private Markdown report: {markdown_path}")
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

    p_news = sub.add_parser(
        "news",
        help="Fetch and store news for tickers (manual twin of the news-ingest worker)",
    )
    p_news.add_argument("tickers", nargs="*", help="Defaults to every active symbol")
    p_news.set_defaults(fn=_cmd_news)

    new_york_today = datetime.now(ZoneInfo("America/New_York")).date()
    p_shadow = sub.add_parser(
        "market-shadow",
        help="Privately compare Massive daily bars with yfinance; never persists or serves data",
    )
    p_shadow.add_argument("tickers", nargs="*", help="Defaults to the representative US set")
    p_shadow.add_argument(
        "--from",
        dest="from_date",
        default=_five_years_before(new_york_today).isoformat(),
        help="First requested session date (YYYY-MM-DD)",
    )
    p_shadow.add_argument(
        "--to",
        dest="to_date",
        default=new_york_today.isoformat(),
        help="Last requested session date (YYYY-MM-DD)",
    )
    p_shadow.add_argument(
        "--output-dir",
        default=str(DEFAULT_SHADOW_OUTPUT),
        help="Private artifact root (default: artifacts/private/massive-shadow)",
    )
    p_shadow.set_defaults(fn=_cmd_market_shadow)

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
