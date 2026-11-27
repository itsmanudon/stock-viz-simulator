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
from collections import Counter
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo

from sqlmodel import Session

from stockviz.db import engine
from stockviz.logging_setup import configure_logging, redact
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
from stockviz.services.instruments import instrument_of
from stockviz.services.metrics import refresh_symbol_metrics
from stockviz.services.trading import credit_due_dividends, snapshot_user_navs
from stockviz.settings import get_settings

logger = logging.getLogger(__name__)

DEFAULT_SHADOW_SYMBOLS = ["AAPL", "MSFT", "NVDA", "AMZN", "META", "TSLA", "JPM"]
VOLUME_PRECISION_PROBES = ["C", "GE", "AIG"]
DEFAULT_SHADOW_OUTPUT = Path("artifacts/private/massive-shadow")


def _cmd_seed(_args: argparse.Namespace) -> int:
    from stockviz.services.checklist.dimensions import seed_dimensions
    from stockviz.services.setups.presets import seed_presets

    with Session(engine) as session:
        n = seed_symbols(session)
        presets = seed_presets(session)  # A2.2: the read-only system setups
        presets |= seed_dimensions(session)  # A2.4: the checklist dimensions
    print(f"seeded {n} symbols")
    for key, state in presets.items():
        print(f"preset {key}: {state}")
    return 0


def _cmd_doctor(_args: argparse.Namespace) -> int:
    """A10.1: read-only health of a self-hosted instance; exit 1 on a failed check."""
    from stockviz.services import doctor
    from stockviz.settings import get_settings

    with Session(engine) as session:
        checks = doctor.run(session, get_settings())
    print(doctor.render(checks))
    return 1 if any(c.status == "fail" for c in checks) else 0


def _cmd_backfill(args: argparse.Namespace) -> int:
    with Session(engine) as session:
        ensure_symbols_for_backfill(session)
        written = backfill_price_bars_from_csvs(session, replace=args.replace)
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


def _cmd_sentiment_aggregate(_args: argparse.Namespace) -> int:
    from stockviz._time import utcnow
    from stockviz.services.aegis.read import refresh_aegis_sentiment

    # Aegis is the sentiment source since Phase 2 (audit AG-14).
    with Session(engine) as session:
        updated = refresh_aegis_sentiment(session, now=utcnow())
    print(f"refreshed rolling Aegis sentiment for {updated} symbols")
    return 0


def _cmd_metrics(_args: argparse.Namespace) -> int:
    with Session(engine) as session:
        written = refresh_symbol_metrics(session)
    print(f"refreshed metrics for {written} symbols")
    return 0


def _cmd_checklist(_args: argparse.Namespace) -> int:
    """Judge the six checklist dimensions for every active symbol (A2.4)."""
    from stockviz.services.checklist.score import run_checklist

    with Session(engine) as session:
        run = run_checklist(session)
    spread = ", ".join(f"{k} met: {v}" for k, v in sorted(run.met_histogram.items(), reverse=True))
    sessions = ", ".join(f"{v} {d.isoformat()}" for v, d in sorted(run.sessions.items()))
    print(f"checklist: {run.symbols} symbols ({sessions or 'no sessions'}); {spread or 'none'}")
    return 0


def _cmd_checklist_evidence(args: argparse.Namespace) -> int:
    """Grade every checklist dimension on the stored history (A2.4)."""
    from stockviz.services.checklist.evidence import run_evidence

    with Session(engine) as session:
        run = run_evidence(session, end=args.end, start=args.start, horizon=args.horizon)
        print(f"checklist-evidence: window {run.start} to {run.end}")
        for row in run.rows:
            excess = f"{row.mean_excess:+.4f}" if row.mean_excess is not None else "n/a"
            t = f"{row.t_stat:.2f}" if row.t_stat is not None else "n/a"
            hit = f"{row.hit_rate:.2f}" if row.hit_rate is not None else "n/a"
            print(
                f"  {row.dimension}/{row.scope} (setup version {row.setup_version_id}): grade {row.grade}, "
                f"n={row.n_events} over {row.symbols} symbols, mean excess {excess}, t {t}, "
                f"hit {hit}, universe {row.universe}"
                + (" (survivorship-biased)" if row.survivorship_biased else "")
            )
    return 0


def _cmd_dividends(args: argparse.Namespace) -> int:
    failures: list[str] = []
    with Session(engine) as session:
        results = ingest_dividends_for_all(session, only=args.tickers or None, failures=failures)
    total = sum(results.values())
    print(f"ingested {total} dividend rows across {len(results)} tickers")
    for ticker, n in sorted(results.items()):
        if n:
            print(f"  {ticker}: {n}")
    if failures:
        # A missed fetch can mean a missed payout (audits MD-4, LG-12).
        print(f"dividends: fetch failed for {', '.join(failures)}", file=sys.stderr)
        return 1
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


def _cmd_outbox_dead(_args: argparse.Namespace) -> int:
    """OP-12: list outbox events that will not be retried. Read-only."""
    from stockviz.events.outbox import dead_events

    with Session(engine) as session:
        rows = dead_events(session)
    for row in rows:
        print(
            f"{row.created_at.isoformat()} {row.event_type} key={row.partition_key} "
            f"attempts={row.publish_attempts} error={(row.last_error or '')[:160]}"
        )
    print(f"{len(rows)} dead outbox event(s)")
    return 0


def _cmd_earnings_duplicates(_args: argparse.Namespace) -> int:
    """RS-10: rows left by date moves before Phase 7.5. Lists; never deletes."""
    from stockviz.services.ingest.earnings import duplicate_upcoming

    with Session(engine) as session:
        found = duplicate_upcoming(session)
    if not found:
        print("no tickers with more than one upcoming report date close together")
        return 0
    for ticker, days in found:
        print(f"{ticker}: {', '.join(d.isoformat() for d in days)}")
    print(f"{len(found)} ticker(s); removing the stale rows needs the owner's approval")
    return 0


def _cmd_non_session_bars(args: argparse.Namespace) -> int:
    """MD-9 (A0): daily bars dated on a day their venue was closed.

    Lists by default. ``--apply`` deletes the weekend ones for the tickers
    named (there is no all-tickers delete), in one transaction.
    """
    from stockviz.services.ingest.non_session_bars import (
        delete_weekend_bars,
        find_non_session_bars,
    )

    tickers = [t.upper() for t in args.tickers]
    if args.apply and not tickers:
        print("--apply needs the tickers to clean, e.g. RELIANCE.NS INFY.NS")
        return 2
    with Session(engine) as session:
        reports = find_non_session_bars(session, tickers or None)
        if not reports:
            print("no daily bars on closed days")
            return 0
        for r in reports:
            sources = ", ".join(f"{s} {n}" for s, n in r.sources.most_common())
            span = f"{min(r.weekend + r.holiday)} to {max(r.weekend + r.holiday)}"
            print(
                f"{r.ticker} ({r.venue}): weekend {len(r.weekend)}, holiday {len(r.holiday)}, "
                f"repeat the previous bar {r.repeats}; {span}; sources: {sources}"
            )
        weekend = sum(len(r.weekend) for r in reports)
        holiday = sum(len(r.holiday) for r in reports)
        print(f"{len(reports)} ticker(s): {weekend} weekend bar(s), {holiday} holiday bar(s)")
        if not args.apply:
            print("dry run: nothing deleted (--apply TICKERS deletes the weekend bars)")
            return 0
        deleted = delete_weekend_bars(session, tickers)
        session.commit()
    for ticker, n in deleted.items():
        print(f"deleted {ticker}: {n}")
    print(f"deleted {sum(deleted.values())} weekend bar(s); run `metrics` next")
    return 0


def _cmd_corporate_actions(args: argparse.Namespace) -> int:
    """Record splits for ledger tickers, then rebase the ledger for due ones (#65).

    Runs after ``ingest`` (which rewrites the split-adjusted closes) and before
    ``settle-orders``, so orders settle on the new scale. Exit 1 if any fetch
    failed: a missed split leaves positions on the old scale.
    """
    from stockviz._time import utcnow
    from stockviz.services.corporate_actions.apply import apply_due_splits
    from stockviz.services.corporate_actions.splits import ledger_tickers, record_splits

    failed: list[str] = []
    recorded = 0
    with Session(engine) as session:
        tickers = [t.upper() for t in args.tickers] if args.tickers else ledger_tickers(session)
        for ticker in tickers:
            try:
                recorded += record_splits(session, ticker)
                session.commit()
            except Exception as exc:
                session.rollback()
                logger.warning("corporate-actions: %s split fetch failed: %s", ticker, exc)
                failed.append(ticker)
        result = apply_due_splits(session, now=utcnow().replace(tzinfo=UTC))
    print(
        f"corporate actions: {len(tickers)} ticker(s) checked, {recorded} split row(s) "
        f"recorded, {result.actions_due} due, {result.users_rebased} user(s) rebased"
    )
    for line in result.summaries:
        print(f"  {line}")
    if failed:
        print(f"corporate-actions: fetch failed for {', '.join(failed)}", file=sys.stderr)
        return 1
    return 0


def _cmd_credit_dividends(_args: argparse.Namespace) -> int:
    from stockviz._time import utcnow
    from stockviz.services.markets.calendar import trading_date

    today = trading_date(utcnow().replace(tzinfo=UTC))
    with Session(engine) as session:
        n = credit_due_dividends(session, credit_date=today)
    print(f"credited {n} portfolio(s) for dividends on {today}")
    return 0


def _cmd_snapshot(_args: argparse.Namespace) -> int:
    """Write each user's NAV dated by the session its prices come from (LG-2)."""
    from stockviz._time import utcnow
    from stockviz.services.ingest.bar_semantics import latest_completed_session

    session_date = latest_completed_session(utcnow().replace(tzinfo=UTC))
    with Session(engine) as session:
        n = snapshot_user_navs(session, snapshot_date=session_date)
    print(f"wrote {n} portfolio snapshots for the {session_date} session")
    return 0


def fetch_option_chain(ticker: str):
    """Network fetch of one listed chain (yfinance); see services/options/chains.py."""
    from stockviz.services.options.chains import yfinance_chain

    return yfinance_chain(ticker)


def _cmd_options_snapshot(args: argparse.Namespace) -> int:
    """Phase 9.6: store tonight's option chains for US stocks (or ``tickers``).

    Exit 1 only when every ticker failed: one stock without listed options or
    a single provider error is reported and the rest are stored.
    """
    from sqlmodel import select

    from stockviz._time import utcnow
    from stockviz.models import Symbol
    from stockviz.services.markets.calendar import trading_date
    from stockviz.services.options.chains import snapshot_all

    today = trading_date(utcnow().replace(tzinfo=UTC))
    with Session(engine) as session:
        tickers = [t.upper() for t in args.tickers] or [
            row.ticker
            for row in session.exec(
                select(Symbol).where(Symbol.is_active, Symbol.currency == "USD")
            ).all()
            if not row.ticker.startswith("^")
        ]
        stored, failed = snapshot_all(
            session, tickers, snapshot_date=today, fetch=fetch_option_chain
        )
    print(
        f"options-snapshot: {len(tickers) - len(failed)} of {len(tickers)} tickers, "
        f"{stored} contracts stored for {today}"
    )
    if failed:
        print(f"options-snapshot: failed: {', '.join(failed[:20])}")
    return 1 if tickers and len(failed) == len(tickers) else 0


def _cmd_settle_options(_args: argparse.Namespace) -> int:
    from stockviz._time import utcnow
    from stockviz.services.markets.calendar import trading_date
    from stockviz.services.options import settle_expired_options

    today = trading_date(utcnow().replace(tzinfo=UTC))
    with Session(engine) as session:
        n = settle_expired_options(session, settle_date=today)
    print(f"settled {n} expired option position(s) as of {today}")
    return 0


def _cmd_prune_trials(args: argparse.Namespace) -> int:
    """A4.3: delete trial-ledger rows not run for ``--days`` (not scheduled)."""
    from stockviz.services.backtest.trials import prune_trials

    if args.days < 1:
        print("--days must be at least 1")
        return 2
    with Session(engine) as session:
        n = prune_trials(session, days=args.days)
    print(f"pruned {n} backtest trial(s) not run for {args.days} day(s)")
    return 0


def _cmd_prune_events(args: argparse.Namespace) -> int:
    from stockviz._time import utcnow
    from stockviz.events.prune import prune_events

    with Session(engine) as session:
        result = prune_events(
            session,
            now=utcnow(),
            retention_days=args.days,
            include_unpublished=args.include_unpublished,
        )
        session.commit()
        from stockviz.services.notifications import prune_read

        notices = prune_read(session)
    print(
        f"pruned events older than {args.days} day(s): {result.published} published outbox, "
        f"{result.unpublished} unpublished outbox, {result.inbox} inbox, "
        f"{result.auth_counters} expired sign-in counters, "
        f"{notices} read notifications over 180 days old"
    )
    return 0


def _cmd_redate_bars(args: argparse.Namespace) -> int:
    """Replace the yfinance daily bars stored a day early (batch 4.1b).

    Dry run unless ``--apply``: lists each affected ticker and the rows it
    would replace. With ``--apply`` each ticker is fetched again from
    yfinance and swapped in its own transaction; see
    ``services/ingest/redate.py``. Exit 1 if any ticker raised.
    """
    from stockviz.services.ingest.redate import (
        count_stored,
        misdated_tickers,
        redate_ticker,
        was_misdated,
    )

    with Session(engine) as session:
        tickers = (
            [t.upper() for t in args.tickers if was_misdated(t.upper())]
            if args.tickers
            else misdated_tickers(session)
        )
        if not args.apply:
            total_bars = total_quarantine = 0
            for ticker in tickers:
                bars, quarantine = count_stored(session, ticker)
                total_bars += bars
                total_quarantine += quarantine
                print(f"  {ticker}: {bars} bars, {quarantine} quarantine rows")
            print(
                f"dry run: {len(tickers)} ticker(s), {total_bars} bars and "
                f"{total_quarantine} quarantine rows would be replaced; pass --apply"
            )
            return 0

    failed: list[str] = []
    replaced = written = 0
    for ticker in tickers:
        try:
            with Session(engine) as session:
                result = redate_ticker(session, ticker)
        except Exception as exc:
            logger.exception("redate-bars: %s failed", ticker)
            print(f"  {ticker}: FAILED ({exc.__class__.__name__}: {exc})", file=sys.stderr)
            failed.append(ticker)
            continue
        if result.skipped:
            print(f"  {ticker}: skipped, yfinance returned nothing; stored rows kept")
            continue
        replaced += result.deleted_bars
        written += result.written
        print(
            f"  {ticker}: deleted {result.deleted_bars} bars and "
            f"{result.deleted_quarantine} quarantine rows, wrote {result.written}"
        )
    print(f"redated {len(tickers) - len(failed)} ticker(s): {replaced} bars out, {written} in")
    return 1 if failed else 0


def _cmd_instrument_check(_args: argparse.Namespace) -> int:
    """Report rows whose ``instrument_id`` the dual-write triggers missed (Phase 4.3).

    Read-only. For every table with a ``ticker`` column: rows with a ticker
    but no ``instrument_id``, and rows whose ``instrument_id`` disagrees with
    the ticker's current ``yahoo`` identifier. Exit 1 if any table has either.
    """
    from sqlalchemy import text

    from stockviz.services.instruments import TICKER_TABLES

    bad = False
    with Session(engine) as session:
        instruments = session.execute(text("SELECT count(*) FROM instruments")).scalar_one()
        symbols = session.execute(text("SELECT count(*) FROM symbols")).scalar_one()
        unmapped = session.execute(
            text(
                "SELECT count(*) FROM symbols s WHERE NOT EXISTS (SELECT 1 FROM "
                "instrument_identifiers i WHERE i.scheme = 'yahoo' AND i.value = s.ticker "
                "AND i.valid_to IS NULL)"
            )
        ).scalar_one()
        print(f"instruments: {instruments} for {symbols} symbol(s), {unmapped} symbol(s) unmapped")
        bad = bad or unmapped > 0
        for table in TICKER_TABLES:
            rows, missing, wrong = session.execute(
                text(
                    f"SELECT count(*), "
                    f"count(*) FILTER (WHERE t.ticker IS NOT NULL AND t.instrument_id IS NULL), "
                    f"count(*) FILTER (WHERE t.instrument_id IS DISTINCT FROM i.instrument_id "
                    f"AND t.ticker IS NOT NULL) "
                    f"FROM {table} t LEFT JOIN instrument_identifiers i ON i.scheme = 'yahoo' "
                    f"AND i.value = t.ticker AND i.valid_to IS NULL"
                )
            ).one()
            flag = "" if missing == 0 and wrong == 0 else "  <- check"
            print(f"  {table}: {rows} rows, {missing} missing, {wrong} mismatched{flag}")
            bad = bad or missing > 0 or wrong > 0
    return 1 if bad else 0


def _cmd_fundamentals(args: argparse.Namespace) -> int:
    """Fetch company fundamentals and append them point-in-time (Phase 6.3).

    ``--source yfinance`` (default): every active equity, not point-in-time.
    ``--source edgar``: US equities, point-in-time; exit 2 without
    ``SEC_USER_AGENT``. Exit 1 if any symbol failed.
    """
    from stockviz._time import utcnow
    from stockviz.services.fundamentals import ingest as fi

    settings = get_settings()
    with Session(engine) as session:
        if args.source == "edgar":
            if not settings.sec_user_agent.strip():
                print("SEC_USER_AGENT is not set: EDGAR is off")
                return 2
            tickers = [t.upper() for t in args.tickers] or fi.equity_tickers(session, country="US")
            report = fi.ingest(session, tickers, fi.edgar_fetcher(settings.sec_user_agent))
        else:
            tickers = [t.upper() for t in args.tickers] or fi.equity_tickers(session)
            report = fi.ingest(
                session,
                tickers,
                fi.yfinance_fetcher(utcnow().date()),
                pause=fi.YFINANCE_GAP_SECONDS,
            )
    print(
        f"fundamentals ({args.source}): {len(report.written)} symbols, "
        f"{sum(report.written.values())} facts written, {len(report.failed)} failed"
    )
    for ticker, reason in report.failed.items():
        print(f"  {ticker}: {reason}")
    return 1 if report.failed else 0


REVALIDATE_HEADER = "X-StockViz-Revalidate"
REVALIDATE_LABEL = b"stockviz-revalidate-v1"


def revalidate_key(secret: str) -> str:
    """HMAC-SHA256 of a fixed label under INTERNAL_API_TOKEN (web checks the same)."""
    import hashlib
    import hmac

    return hmac.new(secret.encode(), REVALIDATE_LABEL, hashlib.sha256).hexdigest()


def _cmd_revalidate_web(_args: argparse.Namespace) -> int:
    """Ask the web server to drop cached market data (audit RS-9, Phase 6.6).

    Exit 2 when ``WEB_REVALIDATE_URL`` is unset; 1 when the web rejects the
    key (a configuration error); 0 otherwise, including when the web cannot
    be reached: a sleeping web holds no cache, it starts empty on wake.
    """
    import httpx

    settings = get_settings()
    url = settings.web_revalidate_url.strip()
    if not url:
        print("WEB_REVALIDATE_URL is not set: skipping web revalidation")
        return 2
    try:
        response = httpx.post(
            url,
            headers={REVALIDATE_HEADER: revalidate_key(settings.internal_api_token)},
            timeout=30.0,
        )
    except httpx.HTTPError as exc:
        print(
            f"web revalidation not delivered ({type(exc).__name__}); its cache refreshes on its own"
        )
        return 0
    if response.status_code in (401, 403):
        print(f"web rejected the revalidation key ({response.status_code})")
        return 1
    if response.status_code >= 400:
        print(f"web revalidation answered {response.status_code}; its cache refreshes on its own")
        return 0
    print(f"web revalidated: {response.text[:200]}")
    return 0


def _cmd_benchmark_kernel(args: argparse.Namespace) -> int:
    """Kernel + SimLedger throughput on a seeded walk (Phase 5.1). No database."""
    from stockviz.benchmarks.kernel import run

    result = run(bars=args.bars)
    print(
        f"{result.bars} bars in {result.seconds:.3f}s: "
        f"{result.fills_per_second:,.0f} fills/s (kernel evaluate + SimLedger apply)"
    )
    return 0


def _cmd_kite_login_url(_args: argparse.Namespace) -> int:
    """Print Zerodha's login page for the Kite app (Phase 4.7). Exit 2 without a key."""
    from stockviz.services.ingest.providers.kite import login_url

    settings = get_settings()
    if not settings.kite_api_key:
        print("KITE_API_KEY is not set: Kite is off")
        return 2
    print(login_url(settings.kite_api_key))
    print(
        "Log in there. Zerodha redirects to the app's redirect address with "
        "?request_token=...; pass it to `ingest-history --provider kite --request-token`."
    )
    return 0


def _record_kite_run(*, ok: bool, summary: str | None = None) -> None:
    """One ``job_runs`` row per Kite snapshot attempt (A5.7: broker status).

    Written only once the command reaches Kite (keys and a request token
    set). Never holds the token, the key or Kite's message text. Recording
    never changes the command's result.
    """
    from stockviz.services.brokers import KITE_SNAPSHOT_JOB, record_provider_run

    try:
        with Session(engine) as session:
            record_provider_run(session, KITE_SNAPSHOT_JOB, ok=ok, summary=summary)
    except Exception:
        logger.exception("job_runs: could not record the Kite snapshot run")


def _cmd_ingest_history(args: argparse.Namespace) -> int:
    """One-off full-history pull from an optional provider (Phase 4.7).

    Dry run unless ``--apply``: per ticker, bars fetched, new days, overlap
    with stored bars and the largest close difference there. Exit 2 when the
    provider is not configured, 1 if any ticker failed.
    """
    from datetime import date as date_type

    from stockviz.services.ingest.history import indian_tickers, snapshot

    if args.provider != "kite":
        print(f"provider {args.provider!r}: no adapter yet (TrueData comes with its trial)")
        return 2
    import httpx

    from stockviz.services.ingest.providers.kite import KiteError, kite_symbol, open_session

    settings = get_settings()
    if not (settings.kite_api_key and settings.kite_api_secret):
        print("KITE_API_KEY and KITE_API_SECRET are not set: Kite is off")
        return 2
    if not args.request_token:
        print("--request-token is required; get one with `stockviz.cli kite-login-url`")
        return 2
    try:
        client = open_session(settings.kite_api_key, settings.kite_api_secret, args.request_token)
    except (KiteError, httpx.HTTPError) as exc:
        # The message is Kite's error type and text (or httpx's class name):
        # never the token. The job row keeps a fixed summary only.
        print(f"Kite login failed: {exc if isinstance(exc, KiteError) else type(exc).__name__}")
        _record_kite_run(ok=False, summary="Kite login failed")
        return 1

    tokens: dict[str, dict[str, int]] = {}
    end = date_type.today()
    provider_errors = 0

    def fetch(ticker: str):
        nonlocal provider_errors
        venue = kite_symbol(ticker)
        if venue is None:
            raise ValueError("not an NSE or BSE ticker")
        exchange, symbol = venue
        try:
            if exchange not in tokens:
                tokens[exchange] = client.instrument_tokens(exchange)
            token = tokens[exchange].get(symbol)
            if token is None:
                raise ValueError(f"{exchange}:{symbol} not in Kite's instrument list")
            return client.daily_bars(ticker, token, end=end), str(token)
        except (KiteError, httpx.HTTPError):
            # A provider error (not a ticker Kite does not list) marks the
            # broker offline on /v1/broker/status (A5.7).
            provider_errors += 1
            raise

    with Session(engine) as session:
        tickers = [t.upper() for t in args.tickers] or indian_tickers(session)
        reports = snapshot(session, tickers, fetch, scheme="kite", apply=args.apply)
    _record_kite_run(
        ok=provider_errors == 0,
        summary=f"Kite error on {provider_errors} ticker(s)" if provider_errors else None,
    )
    failed = False
    for r in reports:
        if r.error:
            failed = True
            print(f"  {r.ticker}: FAILED {r.error}")
            continue
        print(
            f"  {r.ticker}: {r.fetched} bars, {r.new_days} new days, {r.overlap} overlap, "
            f"max close diff {r.max_close_diff_pct}%"
            + (f", {r.written} written" if args.apply else "")
        )
    if not args.apply:
        print(
            "dry run: nothing written. Check the overlap differences and the provider's "
            "data terms (redistribution) before --apply."
        )
    return 1 if failed else 0


def _cmd_instrument_verify(_args: argparse.Namespace) -> int:
    """Compare totals read through the ticker and through the instrument (Phase 4.6a).

    Read-only. Run before the NOT NULL migration and after it. Exit 1 on any
    NULL ``instrument_id`` or any portfolio or symbol whose totals differ.
    """
    from stockviz.services.instruments.verify import verify_identity

    with Session(engine) as session:
        report = verify_identity(session)
    print(f"portfolios: {report.portfolios}, symbols with daily bars: {report.symbols_with_bars}")
    for table, count in report.nulls.items():
        print(f"  NULL instrument_id: {table} {count}")
    for key, ticker, instrument in report.portfolio_diffs:
        print(f"  portfolio {key}: by ticker {ticker}, by instrument {instrument}")
    for key, ticker, instrument in report.bar_diffs:
        print(f"  bars {key}: by ticker {ticker}, by instrument {instrument}")
    print("identity verified" if report.ok else "identity check FAILED")
    return 0 if report.ok else 1


def _cmd_nse_load(args: argparse.Namespace) -> int:
    """Parse NSE end-of-day files placed by hand (A1.1). Nothing downloads.

    Dry run unless ``--apply``: per file, the format, date, rows, matched and
    unmatched rows and what would load; nothing is written, not even the
    archive. ``--apply`` archives each file, records it in ``data_files`` and
    loads it. Exit 1 if any file failed, was unrecognised or had the wrong
    date; a file already recorded (same SHA-256) is a no-op.
    """
    from stockviz.services.nse.process import process_file

    failed = False
    with Session(engine) as session:
        for raw in args.paths:
            report = process_file(session, Path(raw), apply=args.apply)
            failed = failed or not report.ok
            day = report.trading_date.isoformat() if report.trading_date else "-"
            print(f"{report.path}: {report.status} ({report.source}, {day})")
            if report.error:
                print(f"  {report.error}")
            plan = report.plan
            if plan is not None:
                print(
                    f"  rows {plan.rows_total}, in loaded series {plan.in_series}, "
                    f"matched {plan.matched}, unmatched {plan.unmatched}, "
                    f"incomplete {plan.incomplete}, isin conflicts {plan.isin_conflicts}, "
                    f"new isin identifiers {len(plan.isins_to_record)}"
                )
                if plan.unmatched_symbols:
                    print(
                        f"  unmatched (first {len(plan.unmatched_symbols)}): "
                        + ", ".join(plan.unmatched_symbols)
                    )
                if report.result is not None:
                    r = report.result
                    print(
                        f"  loaded {r.loaded} ({r.inserted} new, {r.updated} updated, "
                        f"{r.unchanged} unchanged), isin identifiers recorded {r.isins_recorded}"
                    )
                elif not args.apply:
                    print(f"  would load {plan.matched}")
            if report.archived_path and args.apply:
                print(f"  archived at {report.archived_path} (data_files id {report.data_file_id})")
    if not args.apply:
        print("dry run: nothing written. Run with --apply to archive and load.")
    return 1 if failed else 0


def _cmd_export_parquet(args: argparse.Namespace) -> int:
    """Write the spine tables as monthly zstd Parquet with a manifest (A1.6, M1.8).

    For the laptop's ``lab/`` package. Read-only on the database. ``--since``
    re-exports only months on or after it. Refuses an ``--out`` inside the git
    work tree that git would not ignore: exports hold exchange data.
    """
    from stockviz.services.export.parquet import (
        ExportError,
        export_parquet,
        inside_unignored_worktree,
    )

    out = Path(args.out)
    if inside_unignored_worktree(out):
        print(
            f"refusing {out}: it is inside the repository and not git-ignored. "
            "Exports hold exchange data and are never committed; use a path outside "
            "the repository or under lab/data/."
        )
        return 1
    since = date.fromisoformat(args.since) if args.since else None
    try:
        report = export_parquet(engine, out, since=since, tables=args.tables)
    except ExportError as exc:
        print(f"export failed: {exc}")
        return 1
    for t in report.tables:
        if t.status == "empty":
            print(f"{t.name}: empty, skipped")
            continue
        mode = "full" if t.full else f"since {report.manifest['since']}"
        entry = report.manifest["tables"][t.name]
        print(
            f"{t.name} ({mode}): wrote {t.partitions_written} partition(s), "
            f"{t.rows_written} rows; kept {t.partitions_kept}, removed {t.partitions_removed}; "
            f"{entry['rows']} rows in {len(entry['partitions'])} partition(s) in total"
        )
    m = report.manifest
    print(
        f"manifest {out / 'manifest.json'} (schema {m['schema_version']}, "
        f"commit {m['source_commit']}, exported {m['exported_at']})"
    )
    return 0


def _cmd_intraday_load(args: argparse.Namespace) -> int:
    """Load the owner's intraday files into ``intraday_bars`` (A6.1). Local databases only.

    Dry run unless ``--apply``: per file, rows, rejected, duplicates,
    off-session rows (by day), already stored and new, with a progress line.
    ``--kind moneycontrol`` never writes: it reconciles each file with the
    stored bulk 1-minute bars. Refuses any database not on localhost,
    127.0.0.1 or ::1 (exit 2); nothing overrides it. Exit 1 if a file failed.
    """
    import time as clock

    from stockviz.services.intraday.files import KINDS
    from stockviz.services.intraday.guard import RemoteDatabaseRefused, require_local_database
    from stockviz.services.intraday.load import FileReport, files_in, load_files
    from stockviz.services.intraday.reconcile import reconcile_moneycontrol

    try:
        require_local_database(engine.url)
    except RemoteDatabaseRefused as exc:
        print(exc)
        return 2
    kind = KINDS[args.kind]
    directory = Path(args.dir)
    if not directory.is_dir():
        print(f"{directory}: not a directory")
        return 1
    files = files_in(directory, kind, args.only)
    if not files:
        print(f"no {kind.key} files in {directory}")
        return 1
    started = clock.monotonic()

    if not kind.stored:
        if args.apply:
            print(
                "moneycontrol files are reconciliation only; nothing is written (--apply ignored)"
            )
        failed = False
        with Session(engine) as session:
            for index, (path, ticker) in enumerate(files, start=1):
                r = reconcile_moneycontrol(session, path, ticker, price_tol_pct=args.tolerance_pct)
                failed = failed or r.status == "failed"
                line = (
                    f"[{index}/{len(files)}] {r.file_name} -> {ticker}: {r.status}; rows {r.rows}, "
                    f"rejected {r.invalid}, off-session {r.off_session} "
                    f"({r.off_session_with_volume} with volume), in session {r.in_session}"
                )
                if r.status == "compared":
                    line += (
                        f"; same instants {r.matched_instants}, only in file {r.only_file}, "
                        f"only stored {r.only_stored}, close beyond {args.tolerance_pct}% "
                        f"{r.close_mismatches} (max {r.max_close_diff_pct:.3f}%)"
                    )
                    if r.daily is not None:
                        d = r.daily
                        fields = ", ".join(f"{k} {v}" for k, v in d.field_mismatches.items() if v)
                        line += f"; sessions {d.compared}, matched {d.matched}"
                        if fields:
                            line += f" (beyond tolerance: {fields})"
                        if d.volume_mismatches:
                            line += f", volume {d.volume_mismatches}"
                        if d.median_volume_ratio is not None:
                            line += f", median volume ratio {d.median_volume_ratio:.3f}"
                print(line + (f" ({r.error})" if r.error else ""))
        print(f"done in {clock.monotonic() - started:.1f}s; nothing written")
        return 1 if failed else 0

    def progress(index: int, total: int, r: FileReport) -> None:
        line = (
            f"[{index}/{total}] {r.file_name} -> {r.ticker} ({r.venue}): {r.status}; "
            f"rows {r.rows_total}, rejected {r.invalid}, duplicate {r.duplicate}, "
            f"off-session {r.off_session}, accepted {r.accepted} over {r.sessions} sessions"
        )
        if r.first_ts and r.last_ts:
            line += f" ({r.first_ts:%Y-%m-%d} to {r.last_ts:%Y-%m-%d} UTC)"
        if r.instrument_id is not None:
            line += f", already stored {r.already_stored}, new {r.new}"
        if args.apply and r.status == "loaded":
            line += f", inserted {r.inserted}"
        if r.is_index:
            line += f"; index (volume not real; {r.nonzero_volume} rows with volume)"
        if r.symbol_created:
            line += "; symbol created"
        if r.would_create_symbol:
            line += "; symbol would be created"
        if r.status == "unmatched":
            line += "; no symbol (use --create-symbols)"
        if r.error:
            line += f"; {r.error}"
        line += f" [{r.seconds:.1f}s]"
        print(line, flush=True)
        if r.off_session_days:
            days = ", ".join(
                f"{d.isoformat()} ({n})" for d, n in sorted(r.off_session_days.items())[:8]
            )
            more = len(r.off_session_days) - 8
            print(f"    off-session days: {days}" + (f" and {more} more" if more > 0 else ""))
        if r.problem_lines:
            print(f"    rejected rows, first lines: {', '.join(map(str, r.problem_lines))}")

    with Session(engine) as session:
        reports = load_files(
            session,
            files,
            kind,
            apply=args.apply,
            create_symbols=args.create_symbols,
            progress=progress,
        )
    total = {
        "rows": sum(r.rows_total for r in reports),
        "rejected": sum(r.invalid for r in reports),
        "duplicate": sum(r.duplicate for r in reports),
        "off_session": sum(r.off_session for r in reports),
        "accepted": sum(r.accepted for r in reports),
        "new": sum(r.new for r in reports if r.instrument_id is not None),
        "inserted": sum(r.inserted for r in reports),
    }
    unmatched = [r.ticker for r in reports if r.status == "unmatched"]
    failed = [r.file_name for r in reports if r.status == "failed"]
    print(
        f"{len(reports)} files in {clock.monotonic() - started:.1f}s: "
        + ", ".join(f"{k.replace('_', '-')} {v}" for k, v in total.items())
    )
    if unmatched:
        print(f"unmatched tickers ({len(unmatched)}): {', '.join(unmatched)}")
    if failed:
        print(f"failed: {', '.join(failed)}")
    if not args.apply:
        print("dry run: nothing written. Run with --apply to load (local databases only).")
    return 1 if failed else 0


def _cmd_intraday_catch_up(args: argparse.Namespace) -> int:
    """A6.6: the SIP catch-up after a live IEX day.

    The live stream stores IEX bars only (one exchange's trades). After the
    close, SIP history (every exchange) is free once it is 15 minutes old, so
    this backfills the watched US symbols' minutes for the latest completed
    New York session (or ``--date``) as feed ``sip``, beside the IEX bars
    (``FEED_RANK`` reads SIP first). It is ``intraday-backfill --provider
    alpaca --feed sip`` with the stream's symbols and day: dry run unless
    ``--apply``, exit 2 without the key or without symbols. Not in the cron.
    """
    from stockviz.db import engine
    from stockviz.services.feeds.base import us_symbol
    from stockviz.services.ingest.bar_semantics import latest_completed_session
    from stockviz.services.stream.replay import watched

    if args.date:
        try:
            day = date.fromisoformat(args.date)
        except ValueError:
            print("--date takes YYYY-MM-DD")
            return 1
    else:
        day = latest_completed_session(datetime.now(UTC))
    with Session(engine) as session:
        wanted = args.symbols or watched(session)
    symbols: list[str] = []
    for ticker in wanted:
        try:
            us_symbol(ticker)
        except ValueError:
            continue  # the catch-up is US only, like the stream
        symbols.append(ticker.upper())
    if not symbols:
        print("no US symbols: name them with --symbols, or add an intraday alert")
        return 2
    return _cmd_intraday_backfill(
        argparse.Namespace(
            provider="alpaca",
            symbols=symbols[:30],
            date_from=day.isoformat(),
            date_to=day.isoformat(),
            feed="sip",
            apply=args.apply,
        )
    )


def _cmd_intraday_backfill(args: argparse.Namespace) -> int:
    """US minute history from a free feed into ``intraday_bars`` (A6.3).

    Dry run unless ``--apply``: the plan (sessions, calls, least time the
    documented rate limit allows); nothing is fetched. ``--apply`` fetches
    and writes, idempotent, and records one ``job_runs`` row with a fixed
    summary. Exit 2 when the provider's key is not set (nothing else runs),
    1 on bad arguments or when any symbol failed. Not in the cron.
    """
    from stockviz.services.brokers import FEED_BACKFILL_JOBS, record_provider_run
    from stockviz.services.feeds import backfill as bf
    from stockviz.services.feeds.backfill import SymbolResult, make_plan, run_backfill
    from stockviz.services.feeds.registry import KEY_ENV_VARS, build_feed

    settings = get_settings()
    options: dict[str, object] = {}
    if args.provider == "alpaca":
        options["feed"] = args.feed
    elif args.feed != "iex":
        print(f"--feed applies to alpaca only ({args.provider} has one feed)")
        return 1
    feed = build_feed(args.provider, settings, **options)
    if not feed.configured:
        print(f"{' and '.join(KEY_ENV_VARS[args.provider])} not set: {feed.label} is off")
        return 2
    try:
        first = date.fromisoformat(args.date_from)
        last = date.fromisoformat(args.date_to)
    except ValueError:
        print("--from and --to take YYYY-MM-DD")
        return 1
    if first > last:
        print("--from must be on or before --to")
        return 1
    try:
        plan = make_plan(feed, args.symbols, first, last, bf.now_utc())
    except ValueError as exc:
        print(f"refused: {exc} (US feeds take US tickers only)")
        return 1
    window = plan.window
    print(
        f"{plan.label} ({plan.provider}), feed {plan.feed}: {len(plan.symbols)} symbol(s), "
        f"{first.isoformat()} to {last.isoformat()}"
    )
    if window is None:
        print("no completed XNYS session minutes in that range: nothing to do")
        return 0
    for note in window.notes:
        print(f"  note: {note}")
    seconds = plan.seconds(feed)
    print(
        f"  {len(window.sessions)} sessions, {window.minutes} regular minutes per symbol "
        f"({window.start:%Y-%m-%d %H:%M} to {window.end:%Y-%m-%d %H:%M} UTC)"
    )
    print(
        f"  calls: {plan.calls_per_symbol} per symbol, {plan.calls} in all; rate limit "
        f"{plan.rate_limits}; at least {seconds / 60:.1f} min of waiting"
    )

    def progress(index: int, total: int, r: SymbolResult) -> None:
        line = f"[{index}/{total}] {r.symbol}: {r.status}"
        if r.status == "written":
            line += (
                f"; fetched {r.fetched}, off-session {r.off_session}, inserted {r.inserted}, "
                f"already stored {r.already_stored}"
            )
        if r.error:
            line += f"; {r.error}"
        print(line, flush=True)

    with Session(engine) as session:
        report = run_backfill(session, feed, plan, apply=args.apply, progress=progress)
        if not args.apply:
            print("dry run: nothing fetched or written. Run with --apply to backfill.")
            return 0
        try:
            record_provider_run(
                session,
                FEED_BACKFILL_JOBS[args.provider],
                ok=not report.errors,
                summary=report.summary(),
            )
        except Exception:
            logger.exception("job_runs: could not record the backfill run")
    unknown = [r.symbol for r in report.results if r.status == "unknown_symbol"]
    if unknown:
        print(f"no symbol in this database (add with `ingest` first): {', '.join(unknown)}")
    if report.stopped:
        print(f"stopped: {report.stopped}")
    print(
        f"done: inserted {sum(r.inserted for r in report.results)}, "
        f"waited {report.waited_seconds:.0f}s for the rate limit"
    )
    return 1 if report.errors else 0


def _cmd_intraday_reconcile(args: argparse.Namespace) -> int:
    """Resample stored intraday bars to daily and compare (A6.1). Read-only.

    Against the stored daily ``price_bars`` (default) or the stored 60-minute
    bars. Per symbol: sessions compared and matched within the tolerances,
    sessions on one side only, mismatches by field, worst differences (in
    percent; no prices). Exit 1 when nothing was compared.
    """
    from stockviz.services.intraday.reconcile import MATCH_RATE_FOR_SYMBOL, reconcile

    with Session(engine) as session:
        reports = reconcile(
            session,
            tickers=args.tickers or None,
            feed=args.feed,
            interval=args.interval,
            against=args.against,
            price_tol_pct=args.tolerance_pct,
            volume_tol_pct=args.volume_tolerance_pct,
        )
    if not reports:
        print(f"no stored {args.feed} {args.interval} bars")
        return 1
    compared = [r for r in reports if r.compared]
    for r in reports:
        rate = f"{r.match_rate * 100:.1f}%" if r.match_rate is not None else "-"
        worst = ", ".join(f"{k} {v:.2f}%" for k, v in sorted(r.worst.items()))
        fields = ", ".join(f"{k} {v}" for k, v in r.field_mismatches.items() if v)
        print(
            f"{r.ticker}: compared {r.compared}, matched {r.matched} ({rate}), "
            f"only {args.interval} {r.only_intraday}, only {args.against} {r.only_reference}"
            + (f"; mismatches: {fields}" if fields else "")
            + (f", volume {r.volume_mismatches}" if r.volume_mismatches else "")
            + ("" if r.volume_checked else "; volume not checked (index)")
            + (
                f"; median volume ratio {r.median_volume_ratio:.3f}"
                if r.median_volume_ratio is not None
                else ""
            )
            + (f"; worst {worst}" if worst else "")
        )
        if args.show and r.mismatches:
            for m in r.mismatches[: args.show]:
                print(f"    {m.day.isoformat()} {m.field} {m.diff_pct:.3f}%")
    matching = sum(1 for r in compared if r.matches)
    print(
        f"{len(reports)} symbols, {len(compared)} with sessions to compare; "
        f"{matching} match on at least {MATCH_RATE_FOR_SYMBOL:.0%} of sessions within "
        f"{args.tolerance_pct}% (prices) and {args.volume_tolerance_pct}% (volume)"
    )
    return 0 if compared else 1


def _cmd_intraday_size(_args: argparse.Namespace) -> int:
    """Report the measured size of ``intraday_bars`` (A6.1). PostgreSQL only; read-only."""
    from stockviz.services.intraday.size import measure

    with engine.connect() as conn:
        try:
            report = measure(conn)
        except RuntimeError as exc:
            print(exc)
            return 2
    for ticker, interval, rows in report.per_symbol:
        print(f"  {ticker} {interval}: {rows} rows")
    mb = 1024 * 1024
    per_row = f"{report.bytes_per_row:.1f}" if report.bytes_per_row is not None else "-"
    print(
        f"intraday_bars: {report.rows} rows in {report.partitions} partitions; "
        f"table {report.table_bytes / mb:.1f} MiB, indexes {report.index_bytes / mb:.1f} MiB, "
        f"total {report.total_bytes / mb:.1f} MiB; {per_row} bytes per row"
    )
    return 0


def _cmd_rule_check(args: argparse.Namespace) -> int:
    """Parse, type-check and judge a Rule DSL rule (A2.1, M4.1). Read-only.

    Prints the canonical form and its hash, then for each ticker met /
    not_met / unknown (with the reason) at ``--date`` or, by default, the
    latest completed session of the ticker's venue, judged on the latest
    stored bar on or before it. Exit 2 on a syntax or type error, 1 when a
    ticker is unknown or has no bar. A rule that reads drawings (A3.3) reads
    ``--user-id``'s; without it those values are unknown.
    """
    from stockviz.models import Symbol
    from stockviz.services.dsl import RuleError, compile_rule, evaluate_at, load_symbol
    from stockviz.services.markets.calendar import latest_completed_session, venue_for_ticker

    try:
        rule = compile_rule(args.rule)
    except RuleError as exc:
        print(exc.pretty())
        return 2
    print(f"canonical: {rule.canonical_text}")
    print(f"hash:      {rule.hash}")
    warm = "the whole history" if rule.lookback is None else f"{rule.lookback} daily bars"
    print(f"type:      {rule.type}; warm-up {warm}")
    if rule.user_scoped:
        owner = f"user {args.user_id}" if args.user_id is not None else "nobody (pass --user-id)"
        print(f"scope:     user-scoped (reads drawings); judged for {owner}")
    code = 0
    with Session(engine) as session:
        for raw in args.tickers:
            ticker = raw.upper()
            if session.get(Symbol, ticker) is None:
                print(f"{ticker}: unknown symbol")
                code = 1
                continue
            venue = venue_for_ticker(ticker)
            target = (
                date.fromisoformat(args.date)
                if args.date
                else latest_completed_session(datetime.now(UTC), venue)
            )
            data = load_symbol(
                session, ticker, end=target, start=target, lookback=rule.lookback,
                needs=rule.needs, user_id=args.user_id,
            )  # fmt: skip
            if data.bars.empty:
                print(f"{ticker}: no daily bars on or before {target.isoformat()}")
                code = 1
                continue
            bar = data.dates[-1]
            stale = "" if bar == target else f" (latest bar; session {target.isoformat()})"
            outcome, rows = evaluate_at(rule, data, bar, explain=args.explain)
            print(f"{ticker} {bar.isoformat()}{stale}: {outcome.status}")
            for reason in outcome.reasons:
                print(f"  unknown because {reason}")
            for row in rows:
                tf = "" if row.timeframe == "daily" else f" [{row.timeframe}]"
                print(f"  {row.text}{tf} = {row.value}")
    return code


def _cmd_nse_files(args: argparse.Namespace) -> int:
    """List the most recent ``data_files`` rows (A1.1). Read-only."""
    from sqlmodel import col, select

    from stockviz.models.data_file import DataFile

    with Session(engine) as session:
        rows = session.exec(
            select(DataFile)
            .order_by(col(DataFile.received_at).desc(), col(DataFile.id).desc())
            .limit(args.limit)
        ).all()
    for f in rows:
        day = f.trading_date.isoformat() if f.trading_date else "-"
        print(
            f"{f.id}  {f.received_at:%Y-%m-%d %H:%M}  {f.source}  {day}  {f.parse_status}  "
            f"rows {f.rows_total}/{f.rows_loaded} loaded  {f.file_name}  {f.sha256[:12]}"
            + (f"  ({f.error[:80]})" if f.error else "")
        )
    print(f"{len(rows)} file(s)")
    return 0


def _refresh_aegis_sentiment() -> None:
    """Roll held Aegis sentiment into sentiment_7d, which the signals vote and
    the screener filter read (audit AG-14). Runs after a failed sync too, so
    the trailing window keeps moving on what is already held."""
    from stockviz._time import utcnow
    from stockviz.services.aegis.read import refresh_aegis_sentiment

    with Session(engine) as session:
        refresh_aegis_sentiment(session, now=utcnow())


def _cmd_aegis_sync(args: argparse.Namespace) -> int:
    from stockviz.services.aegis import AegisClient, AegisError, run_sync
    from stockviz.services.aegis.token import load_signing_key, mint_feed_token

    settings = get_settings()
    if not settings.aegis_configured:
        print(
            "aegis-sync: AEGIS_BASE_URL, AEGIS_SERVICE_TOKEN_KEY, AEGIS_ISSUER and "
            "AEGIS_AUDIENCE must all be set. Skipping.",
            file=sys.stderr,
        )
        return 2

    key = load_signing_key(settings.aegis_service_token_key)

    def token() -> str:
        return mint_feed_token(
            key,
            key_id=settings.aegis_key_id,
            issuer=settings.aegis_issuer,
            audience=settings.aegis_audience,
            client_id=settings.aegis_client_id,
        )

    with AegisClient(
        settings.aegis_base_url, token=token, timeout=settings.aegis_timeout_seconds
    ) as client:
        try:
            result = run_sync(
                engine, client, page_limit=settings.aegis_page_limit, max_pages=args.max_pages
            )
        except AegisError as exc:
            print(f"aegis-sync: failed: {exc}", file=sys.stderr)
            _refresh_aegis_sentiment()
            return 1
    _refresh_aegis_sentiment()
    print(
        f"aegis-sync: run {result.run_id}: {result.pages} page(s), "
        f"{result.upserted} document(s) upserted, {result.withdrawn} withdrawn, "
        f"{result.mappings} mapping(s)"
    )
    return 0


def _cmd_settle_orders(args: argparse.Namespace) -> int:
    """Fill or cancel triggered limit, stop-loss and take-profit orders (audit P0-1)."""
    from stockviz._time import utcnow
    from stockviz.services.ingest.bar_semantics import latest_completed_session
    from stockviz.services.trading.orders import settle_pending_orders

    session_date = (
        date.fromisoformat(args.session_date)
        if args.session_date
        else latest_completed_session(utcnow().replace(tzinfo=UTC))
    )
    with Session(engine) as session:
        filled = settle_pending_orders(session, session_date=session_date)
    print(f"settle-orders: filled {filled} pending order(s) against the {session_date} session")
    return 0


def _cmd_evaluate_alerts(args: argparse.Namespace) -> int:
    """Trigger price alerts whose target the latest stored close has crossed (audit P0-2).

    A6.4: ``--intraday --since T`` judges intraday rule alerts on each closed
    stored bar from ``T`` on instead (local use; not in the cron);
    ``--dry-run`` rolls the session back and only prints the firings."""
    from stockviz.services.alerts import evaluate_pending_alerts

    if getattr(args, "intraday", False):
        return _evaluate_intraday(args)
    with Session(engine) as session:
        triggered = evaluate_pending_alerts(session)
    print(f"evaluate-alerts: triggered {triggered} alert(s)")
    return 0


def _evaluate_intraday(args: argparse.Namespace) -> int:
    from stockviz.services.alerts.intraday import evaluate_intraday_alerts

    if not args.since:
        print("evaluate-alerts --intraday needs --since (ISO instant; naive = UTC)")
        return 1
    try:
        since = datetime.fromisoformat(args.since)
    except ValueError:
        print(f"evaluate-alerts: --since {args.since!r} is not an ISO date or instant")
        return 1
    with Session(engine) as session:
        run = evaluate_intraday_alerts(
            session, since=since, ticker=args.ticker, commit=not args.dry_run
        )
        for event in run.events or []:
            print(f"  {event.dedupe_key}  {event.message}")
        for note in run.skipped or []:
            print(f"  skipped: {note}")
        if args.dry_run:
            session.rollback()
    word = "would fire" if args.dry_run else "fired"
    print(
        f"evaluate-alerts --intraday: {run.alerts} alert(s), {run.bars} bar(s) judged, "
        f"{word} {run.fired}"
    )
    return 0


def _cmd_screen_runs(_args: argparse.Namespace) -> int:
    """Store tonight's members of every screened setup version; notify diffs (A2.3)."""
    from stockviz.services.screen_runs import run_screen_runs

    with Session(engine) as session:
        result = run_screen_runs(session)
    print(
        f"screen-runs: {result.runs} run(s) of {result.versions} version(s) for "
        f"{result.session_date}, {result.notifications} notification(s)"
        + (f", {len(result.failed)} failed: {result.failed}" if result.failed else "")
    )
    return 1 if result.failed else 0


def _cmd_deliver_notifications(args: argparse.Namespace) -> int:
    """Send pending notification deliveries (webhook, email, Telegram; A2.3)."""
    from stockviz.services.delivery import drain, server_available

    channel = args.channel
    if channel is not None and not server_available(channel):
        print(f"deliver-notifications: {channel} is not configured on this server; skipped")
        return 2
    off = [c for c in ("email", "telegram") if not server_available(c)]
    with Session(engine) as session:
        result = drain(session, channel=channel, limit=args.limit)
    print(
        f"deliver-notifications: sent {result.sent}, retrying {result.retrying}, "
        f"dead {result.dead}, skipped {result.skipped}"
        + (f" (off on this server: {', '.join(off)})" if off and channel is None else "")
    )
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


def _cmd_fx(args: argparse.Namespace) -> int:
    currencies = (
        [c.upper() for c in args.currencies] if args.currencies else _default_fx_currencies()
    )
    total = 0
    failed: list[str] = []
    for ccy in currencies:
        try:
            with Session(engine) as session:
                written = ingest_fx(session, ccy)
        except Exception as exc:
            logger.exception("fx: %s failed", ccy)
            print(f"  {ccy}: FAILED ({exc.__class__.__name__}: {exc})", file=sys.stderr)
            failed.append(ccy)
            continue
        print(f"  {ccy}: {written}")
        total += written
        # ingest_fx returns 0 only for USD (a no-op) or when no rates came back.
        if written == 0 and ccy != "USD":
            failed.append(ccy)
    print(f"ingested {total} FX rates total")
    if failed:
        # Fills in these currencies would convert at an old rate (audit MD-4).
        print(f"fx: no rates for {', '.join(failed)}", file=sys.stderr)
        return 1
    return 0


def _cmd_macro_sync(args: argparse.Namespace) -> int:
    """A9.7 (M1.10): fetch the catalogue's FRED series into ``macro_*``."""
    from stockviz.services.feeds.base import FeedNotConfigured
    from stockviz.services.macro.catalogue import BY_ID, CATALOGUE
    from stockviz.services.macro.fred import FredClient
    from stockviz.services.macro.sync import sync_catalogue

    key = get_settings().fred_api_key.get_secret_value()
    if not key:
        print("macro-sync: FRED_API_KEY is not set", file=sys.stderr)
        return 2
    wanted = [s.upper() for s in (args.series or [])]
    unknown = [s for s in wanted if s not in BY_ID]
    if unknown:
        print(f"macro-sync: not in the catalogue: {', '.join(unknown)}", file=sys.stderr)
        return 1
    entries = [BY_ID[s] for s in wanted] if wanted else list(CATALOGUE)
    try:
        with Session(engine) as session:
            report = sync_catalogue(session, FredClient(key), entries)
    except FeedNotConfigured:
        print("macro-sync: FRED_API_KEY is not set", file=sys.stderr)
        return 2
    for r in report.results:
        print(f"  {r.series_id}: {r.error or r.written}")
    print(f"macro-sync: {report.written} observations over {len(report.results)} series")
    if report.stopped:
        print(f"macro-sync: stopped ({report.stopped})", file=sys.stderr)
    return 1 if report.failed else 0


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


def _latest_daily_bar_date(ticker: str) -> date | None:
    from sqlalchemy import func
    from sqlmodel import select

    from stockviz.models import PriceBar

    with Session(engine) as session:
        latest = session.exec(
            select(func.max(PriceBar.ts)).where(  # type: ignore[call-overload]
                PriceBar.instrument_id == instrument_of(ticker), PriceBar.interval == "1d"
            )
        ).one()
    return latest.date() if latest is not None else None


def _cmd_ingest(args: argparse.Namespace) -> int:
    """Refresh daily bars; exit 1 when the refresh did not work (audit MD-4).

    Row counts prove nothing (the full history is upserted every night), so
    success is judged by the newest stored bar. A ticker that raises is
    reported and the rest still run. The run fails if any ticker raised, or
    if no ticker reached its venue's newest complete session (Phase 4.1:
    exchange calendars, so a market holiday expects the session before). One
    ticker short of it is only reported: its provider may lag.
    """
    from stockviz._time import utcnow
    from stockviz.services.ingest.bar_semantics import latest_completed_session
    from stockviz.services.markets.calendar import venue_for_ticker

    settings = get_settings()
    now = utcnow().replace(tzinfo=UTC)
    expected = latest_completed_session(now)
    reached = False
    total = 0
    failed: list[str] = []
    behind: list[str] = []
    newest: date | None = None
    for raw in args.tickers:
        ticker = raw.upper()
        try:
            with Session(engine) as session:
                written = ingest_ticker(
                    session, ticker, alpha_vantage_key=settings.alpha_vantage_key
                )
        except Exception as exc:
            logger.exception("ingest: %s failed", ticker)
            print(f"  {ticker}: FAILED ({exc.__class__.__name__}: {exc})", file=sys.stderr)
            failed.append(ticker)
            continue
        latest = _latest_daily_bar_date(ticker)
        print(f"  {ticker}: {written} (latest bar {latest})")
        total += written
        ticker_expected = latest_completed_session(now, venue_for_ticker(ticker))
        if latest is None or latest < ticker_expected:
            behind.append(f"{ticker} (expected {ticker_expected})")
        else:
            reached = True
        if latest is not None and (newest is None or latest > newest):
            newest = latest
    print(f"ingested {total} bars total; expected New York session {expected}")
    if behind:
        print(f"ingest: behind: {', '.join(behind)}", file=sys.stderr)
    if failed:
        print(f"ingest: {len(failed)} ticker(s) failed: {', '.join(failed)}", file=sys.stderr)
        return 1
    if args.tickers and not reached:
        print(
            f"ingest: no ticker reached its venue's latest session (newest {newest})",
            file=sys.stderr,
        )
        return 1
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


def _cmd_ingest_quarantine(args: argparse.Namespace) -> int:
    """Inspect or release bars parked by plausibility screening (F-011)."""
    from decimal import Decimal

    from sqlmodel import col, select

    from stockviz.models import QuarantinedPriceBar
    from stockviz.services.ingest.bar_semantics import AdjustmentSemantics, SessionScope
    from stockviz.services.ingest.prices import BarRecord, write_accepted_bars

    with Session(engine) as session:
        if args.release:
            rows = session.exec(
                select(QuarantinedPriceBar).where(col(QuarantinedPriceBar.id).in_(args.release))
            ).all()
            found = {r.id for r in rows}
            for r in rows:
                write_accepted_bars(
                    session,
                    [
                        BarRecord(
                            ticker=r.ticker,
                            ts=r.ts,
                            interval=r.interval,
                            open=r.open,
                            high=r.high,
                            low=r.low,
                            close=r.close,
                            volume=Decimal(r.volume),
                            source=r.source or "quarantine_release",
                            adjustment_semantics=AdjustmentSemantics(
                                r.adjustment_semantics or AdjustmentSemantics.SPLIT_ADJUSTED
                            ),
                            session_scope=SessionScope(r.session_scope or SessionScope.REGULAR),
                        )
                    ],
                )
                session.delete(r)
                print(f"  released #{r.id}: {r.ticker} {r.ts.date()} close={r.close}")
            session.commit()
            missing = sorted(set(args.release) - found)
            for rid in missing:
                print(f"  #{rid} not found", file=sys.stderr)
            return 1 if missing else 0

        stmt = select(QuarantinedPriceBar).order_by(col(QuarantinedPriceBar.detected_at).desc())
        if args.ticker:
            stmt = stmt.where(QuarantinedPriceBar.ticker == args.ticker.upper())
        rows = session.exec(stmt.limit(args.limit)).all()
        if not rows:
            print("no quarantined bars")
            return 0
        for r in rows:
            print(
                f"  #{r.id}  {r.ticker:<6} {r.ts.date()} {r.interval}  "
                f"O={r.open} H={r.high} L={r.low} C={r.close}  "
                f"prev_close={r.prev_close}  — {r.reason}"
            )
        print(f"{len(rows)} row(s); release with: stockviz ingest-quarantine --release <id> ...")
        return 0


def _cmd_indicator_evidence(args: argparse.Namespace) -> int:
    """Grade each study's canonical signal on the stored history (A3.4)."""
    from stockviz.services.indicators.evidence import run_indicator_evidence
    from stockviz.services.indicators.signals import SIGNALS

    unknown = [k for k in args.only or [] if k not in SIGNALS]
    if unknown:
        print(f"indicator-evidence: no canonical signal for {', '.join(unknown)}", file=sys.stderr)
        return 2
    with Session(engine) as session:
        run = run_indicator_evidence(
            session, end=args.end, start=args.start, horizon=args.horizon, only=args.only or None
        )
        print(f"indicator-evidence: window {run.start} to {run.end}")
        for row in run.rows:
            excess = f"{row.mean_excess:+.4f}" if row.mean_excess is not None else "n/a"
            t = f"{row.t_stat:.2f}" if row.t_stat is not None else "n/a"
            print(
                f"  {row.indicator}: grade {row.grade}, n={row.n_events} over {row.symbols} "
                f"symbols, mean excess {excess}, t {t}, universe {row.universe}"
                + (" (survivorship-biased)" if row.survivorship_biased else "")
                + f"  [{row.rule}]"
            )
        return 0


RECORDED_JOBS = frozenset(
    {
        "indicator-evidence",
        "ingest",
        "fundamentals",
        "revalidate-web",
        "corporate-actions",
        "fx",
        "macro-sync",
        "settle-orders",
        "evaluate-alerts",
        "screen-runs",
        "deliver-notifications",
        "aegis-sync",
        "metrics",
        "dividends",
        "credit-dividends",
        "settle-options",
        "options-snapshot",
        "checklist",
        "checklist-evidence",
        "snapshot-portfolios",
        "prune-events",
        "earnings",
        "metadata",
        "sentiment-aggregate",
    }
)
"""The nightly job commands whose runs are written to ``job_runs`` (OP-5).

Long-running workers and one-off maintenance commands are not recorded.
"""


def _start_sentry() -> None:
    """The CLI never started Sentry, so a failed night reported nowhere (OP-5)."""
    try:
        from stockviz.observability import init_sentry

        init_sentry(get_settings())
    except Exception:
        logger.exception("sentry init failed; continuing without it")


def _record_job_start(job: str) -> int | None:
    from stockviz.models import JobRun

    try:
        with Session(engine) as session:
            row = JobRun(job=job)
            session.add(row)
            session.commit()
            session.refresh(row)
            return row.id
    except Exception:
        logger.exception("job_runs: could not record the start of %s", job)
        return None


def _record_job_end(run_id: int | None, code: int, error: str | None) -> None:
    from stockviz._time import utcnow
    from stockviz.models import JobRun

    if run_id is None:
        return
    try:
        with Session(engine) as session:
            row = session.get(JobRun, run_id)
            if row is None:
                return
            row.finished_at = utcnow()
            row.exit_code = code
            row.status = {0: "succeeded", 2: "skipped"}.get(code, "failed")
            # An httpx error message holds the request URL, key included.
            row.error = redact(error)[:4000] if error else None
            session.add(row)
            session.commit()
    except Exception:
        logger.exception("job_runs: could not record the end of run %s", run_id)


def _run_recorded(job: str, run: Callable[[], int]) -> int:
    """Run a job command and write its outcome to ``job_runs``.

    Recording never changes the job's result: if the table cannot be written,
    the job still runs and returns its own exit code.
    """
    run_id = _record_job_start(job)
    try:
        code = run()
    except Exception as exc:
        _record_job_end(run_id, 1, f"{exc.__class__.__name__}: {exc}")
        raise
    _record_job_end(run_id, code, None)
    return code


def main(argv: list[str] | None = None) -> int:
    configure_logging()

    parser = argparse.ArgumentParser(prog="stockviz", description="StockViz API operator commands.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser(
        "seed", help="Seed symbols from companies.json and the rule presets"
    ).set_defaults(fn=_cmd_seed)
    sub.add_parser(
        "doctor", help="Check a self-hosted instance (database, migrations, secrets, keys)"
    ).set_defaults(fn=_cmd_doctor)
    p_backfill = sub.add_parser(
        "backfill", help="Load the seed CSVs into price_bars (run once after seed)"
    )
    p_backfill.add_argument(
        "--replace",
        action="store_true",
        help="first delete each ticker's v1_csv daily bars (fixes a database loaded "
        "from the old, misdated CSVs); live-ingested bars are kept",
    )
    p_backfill.set_defaults(fn=_cmd_backfill)

    p_meta = sub.add_parser(
        "metadata", help="Backfill sector/exchange on existing symbols (yfinance)"
    )
    p_meta.add_argument("tickers", nargs="*", help="Optional ticker filter")
    p_meta.set_defaults(fn=_cmd_metadata)

    p_ingest = sub.add_parser("ingest", help="Refresh daily bars for one or more tickers")
    p_ingest.add_argument("tickers", nargs="+")
    p_ingest.set_defaults(fn=_cmd_ingest)

    p_quar = sub.add_parser(
        "ingest-quarantine",
        help="List (or --release) price bars held back by plausibility screening (F-011)",
    )
    p_quar.add_argument("--ticker", help="Filter the listing to one ticker")
    p_quar.add_argument("--limit", type=int, default=50, help="Max rows to list (default 50)")
    p_quar.add_argument(
        "--release",
        nargs="+",
        type=int,
        metavar="ID",
        help="Write these quarantine rows into price_bars and delete them",
    )
    p_quar.set_defaults(fn=_cmd_ingest_quarantine)

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

    p_macro = sub.add_parser(
        "macro-sync", help="Fetch the macro catalogue's FRED series (A9.7; needs FRED_API_KEY)"
    )
    p_macro.add_argument("--series", nargs="*", help="Only these FRED ids (default: all)")
    p_macro.set_defaults(fn=_cmd_macro_sync)

    sub.add_parser(
        "metrics", help="Recompute the screener's precomputed per-symbol metrics"
    ).set_defaults(fn=_cmd_metrics)

    sub.add_parser(
        "sentiment-aggregate",
        help="Roll Aegis News sentiment into the per-symbol trailing average",
    ).set_defaults(fn=_cmd_sentiment_aggregate)

    sub.add_parser(
        "checklist", help="Judge the six checklist dimensions for every active symbol (A2.4)"
    ).set_defaults(fn=_cmd_checklist)

    p_evidence = sub.add_parser(
        "checklist-evidence",
        help="Grade each checklist dimension: forward returns net of fees vs the base rate",
    )
    p_evidence.add_argument("--start", type=date.fromisoformat, default=None)
    p_evidence.add_argument("--end", type=date.fromisoformat, default=None)
    p_evidence.add_argument("--horizon", type=int, default=20)
    p_evidence.set_defaults(fn=_cmd_checklist_evidence)

    p_ind = sub.add_parser(
        "indicator-evidence",
        help="Grade each indicator's canonical signal (A3.4): the checklist's evidence study",
    )
    p_ind.add_argument("--start", type=date.fromisoformat, default=None)
    p_ind.add_argument("--end", type=date.fromisoformat, default=None)
    p_ind.add_argument("--horizon", type=int, default=20)
    p_ind.add_argument("--only", nargs="*", default=None, help="study keys (default: all)")
    p_ind.set_defaults(fn=_cmd_indicator_evidence)

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
        "outbox-dead", help="List outbox events that exhausted their publish attempts (OP-12)"
    ).set_defaults(fn=_cmd_outbox_dead)
    p_nsb = sub.add_parser(
        "non-session-bars",
        help="List daily bars dated on a closed day (MD-9); --apply deletes the weekend ones",
    )
    p_nsb.add_argument("tickers", nargs="*", help="Tickers to check (all when empty)")
    p_nsb.add_argument(
        "--apply", action="store_true", help="Delete the weekend bars of the tickers named"
    )
    p_nsb.set_defaults(fn=_cmd_non_session_bars)
    sub.add_parser(
        "earnings-duplicates",
        help="List upcoming earnings dates that look like one report stored twice (read-only)",
    ).set_defaults(fn=_cmd_earnings_duplicates)

    sub.add_parser(
        "credit-dividends", help="Credit today's due dividends to all eligible portfolios"
    ).set_defaults(fn=_cmd_credit_dividends)

    sub.add_parser(
        "settle-options", help="Settle every option position that has reached expiry"
    ).set_defaults(fn=_cmd_settle_options)

    p_chain = sub.add_parser(
        "options-snapshot",
        help="Store tonight's option chains (yfinance) for US stocks, or the tickers given",
    )
    p_chain.add_argument("tickers", nargs="*")
    p_chain.set_defaults(fn=_cmd_options_snapshot)

    p_prune = sub.add_parser(
        "prune-events",
        help="Delete outbox and inbox rows past their retention (published rows only by default)",
    )
    p_prune.add_argument(
        "--days",
        type=int,
        default=30,
        help="Keep rows newer than this many days (default 30)",
    )
    p_prune.add_argument(
        "--include-unpublished",
        action="store_true",
        help="Also delete old unpublished outbox rows. Only where no publisher runs, like the Railway cron",
    )
    p_prune.set_defaults(fn=_cmd_prune_events)

    p_trials = sub.add_parser(
        "prune-trials",
        help="Delete backtest trial-ledger rows not run for --days (A4.3; not scheduled)",
    )
    p_trials.add_argument(
        "--days", type=int, default=365, help="Keep rows run within this many days (default 365)"
    )
    p_trials.set_defaults(fn=_cmd_prune_trials)

    p_redate = sub.add_parser(
        "redate-bars",
        help="Replace yfinance daily bars stored a day early on non-US venues (dry run by default)",
    )
    p_redate.add_argument(
        "tickers", nargs="*", help="Limit to these tickers (default: all affected)"
    )
    p_redate.add_argument(
        "--apply", action="store_true", help="Fetch again and replace the rows (default: dry run)"
    )
    p_redate.set_defaults(fn=_cmd_redate_bars)

    p_ca = sub.add_parser(
        "corporate-actions",
        help="Record splits for ledger tickers and rebase positions, orders, alerts, options",
    )
    p_ca.add_argument("tickers", nargs="*", help="Limit the split fetch to these tickers")
    p_ca.set_defaults(fn=_cmd_corporate_actions)

    sub.add_parser(
        "instrument-check",
        help="Read-only: rows whose instrument_id the identity triggers missed (Phase 4.3)",
    ).set_defaults(fn=_cmd_instrument_check)

    p_fund = sub.add_parser(
        "fundamentals", help="Append company fundamentals point-in-time (Phase 6.3)"
    )
    p_fund.add_argument("--source", choices=["yfinance", "edgar"], default="yfinance")
    p_fund.add_argument("tickers", nargs="*", help="Default: every active equity")
    p_fund.set_defaults(fn=_cmd_fundamentals)

    sub.add_parser(
        "revalidate-web", help="Tell the web to drop cached market data (RS-9)"
    ).set_defaults(fn=_cmd_revalidate_web)

    p_bench = sub.add_parser(
        "benchmark-kernel", help="Kernel + SimLedger throughput, no database (Phase 5.1)"
    )
    p_bench.add_argument("--bars", type=int, default=20_000)
    p_bench.set_defaults(fn=_cmd_benchmark_kernel)

    sub.add_parser(
        "kite-login-url", help="Print Zerodha's login page for the Kite app (Phase 4.7)"
    ).set_defaults(fn=_cmd_kite_login_url)

    p_hist = sub.add_parser(
        "ingest-history",
        help="One-off full-history pull from an optional provider; dry run unless --apply",
    )
    p_hist.add_argument("--provider", choices=["kite", "truedata"], required=True)
    p_hist.add_argument("--request-token", default=None, help="Kite: from the login redirect")
    p_hist.add_argument("--apply", action="store_true", help="Write the bars (default: report)")
    p_hist.add_argument("tickers", nargs="*", help="Default: every active NSE/BSE symbol")
    p_hist.set_defaults(fn=_cmd_ingest_history)

    sub.add_parser(
        "instrument-verify",
        help="Read-only: totals through the ticker and the instrument agree (Phase 4.6a)",
    ).set_defaults(fn=_cmd_instrument_verify)

    p_nse = sub.add_parser(
        "nse-load",
        help="Parse NSE EOD files placed by hand (dry run; --apply archives and loads)",
    )
    p_nse.add_argument("paths", nargs="+", help="CM bhavcopy or sec_bhavdata_full files")
    p_nse.add_argument("--apply", action="store_true", help="Archive, record and load")
    p_nse.set_defaults(fn=_cmd_nse_load)
    p_nse_files = sub.add_parser("nse-files", help="List recent recorded NSE files")
    p_nse_files.add_argument("--limit", type=int, default=20)
    p_nse_files.set_defaults(fn=_cmd_nse_files)

    from stockviz.services.export.tables import TABLE_NAMES

    p_export = sub.add_parser(
        "export-parquet",
        help="Write the spine tables as monthly Parquet partitions with a manifest (A1.6)",
    )
    p_export.add_argument("--out", required=True, help="Export directory")
    p_export.add_argument(
        "--since", default=None, help="YYYY-MM-DD; re-export only months on or after it"
    )
    p_export.add_argument(
        "--tables", nargs="+", choices=TABLE_NAMES, default=None, help="Default: all"
    )
    p_export.set_defaults(fn=_cmd_export_parquet)

    p_intra = sub.add_parser(
        "intraday-load",
        help="Load the owner's intraday files (A6.1; local databases only; dry run unless --apply)",
    )
    p_intra.add_argument("--dir", required=True, help="Directory holding the files")
    p_intra.add_argument(
        "--kind", required=True, choices=("bulk1m", "bulk1h", "moneycontrol"), help="File format"
    )
    p_intra.add_argument("--apply", action="store_true", help="Write (bulk1m, bulk1h)")
    p_intra.add_argument(
        "--create-symbols",
        action="store_true",
        help="Add a symbols row (INR, NSE) for a ticker the database lacks (with --apply)",
    )
    p_intra.add_argument("--only", nargs="+", default=None, help="Only these tickers")
    p_intra.add_argument(
        "--tolerance-pct", type=float, default=0.5, help="moneycontrol: price tolerance, percent"
    )
    p_intra.set_defaults(fn=_cmd_intraday_load)
    p_iback = sub.add_parser(
        "intraday-backfill",
        help="US minute history from a free feed (A6.3; dry run unless --apply; needs its key)",
    )
    p_iback.add_argument("--provider", required=True, choices=("alpaca", "tiingo", "massive"))
    p_iback.add_argument("--symbols", nargs="+", required=True, help="US tickers, e.g. AAPL MSFT")
    p_iback.add_argument("--from", dest="date_from", required=True, help="YYYY-MM-DD (New York)")
    p_iback.add_argument("--to", dest="date_to", required=True, help="YYYY-MM-DD, inclusive")
    p_iback.add_argument(
        "--feed",
        default="iex",
        choices=("iex", "sip"),
        help="alpaca: sip needs an end >= 15 min old",
    )
    p_iback.add_argument("--apply", action="store_true", help="Fetch and write (default: plan)")
    p_iback.set_defaults(fn=_cmd_intraday_backfill)
    p_icatch = sub.add_parser(
        "intraday-catch-up",
        help="A6.6: SIP minutes for the watched US symbols after a live IEX day (dry run unless --apply)",
    )
    p_icatch.add_argument(
        "--symbols", nargs="+", default=None, help="Default: the stream's symbols"
    )
    p_icatch.add_argument(
        "--date", default=None, help="YYYY-MM-DD (default: the latest US session)"
    )
    p_icatch.add_argument("--apply", action="store_true", help="Fetch and write (default: plan)")
    p_icatch.set_defaults(fn=_cmd_intraday_catch_up)
    p_irec = sub.add_parser(
        "intraday-reconcile",
        help="Compare stored intraday bars, resampled to daily, with daily or 60m bars (A6.1)",
    )
    p_irec.add_argument("tickers", nargs="*", help="Default: every instrument with bars")
    p_irec.add_argument("--feed", default="file", choices=("file", "iex", "sip", "kite"))
    p_irec.add_argument("--interval", default="1m", choices=("1m", "60m"))
    p_irec.add_argument("--against", default="daily", choices=("daily", "60m"))
    p_irec.add_argument("--tolerance-pct", type=float, default=0.5, help="Prices, percent")
    p_irec.add_argument(
        "--volume-tolerance-pct", type=float, default=10.0, help="Volume ratio, percent"
    )
    p_irec.add_argument("--show", type=int, default=0, help="List the N worst sessions per symbol")
    p_irec.set_defaults(fn=_cmd_intraday_reconcile)
    sub.add_parser(
        "intraday-size", help="Measured size of intraday_bars (A6.1; PostgreSQL)"
    ).set_defaults(fn=_cmd_intraday_size)

    p_rule = sub.add_parser(
        "rule-check",
        help="Parse and type-check a Rule DSL rule and judge it for tickers (A2.1)",
    )
    p_rule.add_argument("rule", help='e.g. "close > sma(close, 200) and rsi(14) < 70"')
    p_rule.add_argument("tickers", nargs="*", help="Symbols to judge the rule for")
    p_rule.add_argument(
        "--date", default=None, help="YYYY-MM-DD; default: the latest completed session"
    )
    p_rule.add_argument("--explain", action="store_true", help="Print every sub-expression's value")
    p_rule.add_argument(
        "--user-id",
        type=int,
        default=None,
        help="Whose drawings drawing()/avwap() read (A3.3); without it they are unknown",
    )
    p_rule.set_defaults(fn=_cmd_rule_check)

    p_aegis = sub.add_parser(
        "aegis-sync",
        help="Copy new Aegis News documents and the mapping list into the read tables",
    )
    p_aegis.add_argument(
        "--max-pages", type=int, default=None, help="Stop after this many feed pages"
    )
    p_aegis.set_defaults(fn=_cmd_aegis_sync)

    p_settle = sub.add_parser(
        "settle-orders",
        help="Fill or cancel triggered pending orders against the latest completed session",
    )
    p_settle.add_argument(
        "--session-date",
        default=None,
        help="YYYY-MM-DD; default: the newest weekday before today's New York date",
    )
    p_settle.set_defaults(fn=_cmd_settle_orders)

    p_alerts = sub.add_parser(
        "evaluate-alerts", help="Trigger price alerts the latest stored close has crossed"
    )
    p_alerts.add_argument(
        "--intraday",
        action="store_true",
        help="A6.4: judge intraday rule alerts on each closed stored bar (local use)",
    )
    p_alerts.add_argument("--since", default=None, help="with --intraday: ISO instant, naive = UTC")
    p_alerts.add_argument("--ticker", default=None, help="with --intraday: one symbol")
    p_alerts.add_argument(
        "--dry-run", action="store_true", help="with --intraday: print, write nothing"
    )
    p_alerts.set_defaults(fn=_cmd_evaluate_alerts)

    sub.add_parser(
        "screen-runs",
        help="Store every screened setup version's members tonight; notify entries and exits",
    ).set_defaults(fn=_cmd_screen_runs)

    p_deliver = sub.add_parser(
        "deliver-notifications",
        help="Send pending notification deliveries (webhook, email, Telegram)",
    )
    p_deliver.add_argument("--channel", choices=["webhook", "email", "telegram"], default=None)
    p_deliver.add_argument("--limit", type=int, default=500)
    p_deliver.set_defaults(fn=_cmd_deliver_notifications)

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
    ):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--once", action="store_true", help="Handle at most one message and exit")
        p.set_defaults(fn=fn)

    args = parser.parse_args(argv)
    _start_sentry()
    if args.cmd not in RECORDED_JOBS or getattr(args, "intraday", False):
        return args.fn(args)
    return _run_recorded(args.cmd, lambda: args.fn(args))


if __name__ == "__main__":
    sys.exit(main())
