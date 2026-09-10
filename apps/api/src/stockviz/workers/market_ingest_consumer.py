"""Consume ``market.refresh.requested``: fetch bars, persist, emit bars.refreshed.

uv --directory apps/api run python -m stockviz.workers.market_ingest_consumer
uv --directory apps/api run python -m stockviz.workers.market_ingest_consumer --once
"""

from __future__ import annotations

import json
import logging
import sys
from collections import Counter
from datetime import date, datetime, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo

from sqlmodel import Session

from stockviz.db import engine
from stockviz.events.contracts import (
    EVENT_TYPE_MARKET_REFRESH_REQUESTED,
    MARKET_INGEST_CONSUMER,
    MARKET_TOPIC,
)
from stockviz.events.dispatcher import worker_main
from stockviz.events.handlers import persist_market_refresh
from stockviz.events.outbox import parse_market_refresh_requested
from stockviz.services.ingest.bar_semantics import completed_daily_bars
from stockviz.services.ingest.prices import BarRecord, fetch_daily_bars
from stockviz.services.ingest.providers.massive import (
    MassiveProviderError,
    MassiveSemanticError,
    fetch_massive_daily,
)
from stockviz.services.ingest.shadow import RawLatestSessions, SymbolComparison, compare_symbol
from stockviz.settings import get_settings

logger = logging.getLogger(__name__)


class ShadowSettings(Protocol):
    massive_shadow_enabled: bool
    massive_api_key: str
    massive_shadow_lookback_days: int


def run_massive_shadow(
    ticker: str,
    reference_bars: list[BarRecord],
    *,
    since: date | None,
    settings: ShadowSettings,
) -> SymbolComparison | None:
    """Run a bounded, in-memory comparison and return no persistence input."""

    if not settings.massive_shadow_enabled:
        return None
    today = datetime.now(ZoneInfo("America/New_York")).date()
    lookback_start = today - timedelta(days=settings.massive_shadow_lookback_days)
    start = max(since, lookback_start) if since is not None else lookback_start
    candidate_raw = fetch_massive_daily(
        ticker,
        start=start,
        end=today,
        api_key=settings.massive_api_key,
    )
    bounded_reference = [bar for bar in reference_bars if start <= bar.ts.date() <= today]
    candidate_completed = completed_daily_bars(candidate_raw)
    result = compare_symbol(
        bounded_reference,
        candidate_completed,
        actions=[],
        raw_latest=RawLatestSessions(
            reference=max((bar.ts.date() for bar in bounded_reference), default=None),
            candidate=max((bar.ts.date() for bar in candidate_raw), default=None),
        ),
    )
    classifications = Counter(item.classification for item in result.discrepancies)
    summary = {
        "ticker": ticker,
        "reference_source": result.reference_source,
        "candidate_source": result.candidate_source,
        "reference_rows": result.reference_rows,
        "candidate_rows": result.candidate_rows,
        "common_sessions": result.common_sessions,
        "reference_only_sessions": len(result.reference_only_sessions),
        "candidate_only_sessions": len(result.candidate_only_sessions),
        "newest_completed_reference": (
            result.newest_completed_reference.isoformat()
            if result.newest_completed_reference is not None
            else None
        ),
        "newest_completed_candidate": (
            result.newest_completed_candidate.isoformat()
            if result.newest_completed_candidate is not None
            else None
        ),
        "classifications": dict(sorted(classifications.items())),
        "close": result.fields["close"].as_dict(),
        "volume": result.volume.as_dict(),
    }
    logger.info("Massive shadow summary %s", json.dumps(summary, sort_keys=True))
    return result


def fetch_bars_for_event(event: object) -> list[BarRecord]:
    """Provider I/O. Tests monkeypatch this. A crash here does not write DB."""
    payload = event.payload  # type: ignore[attr-defined]
    settings = get_settings()
    since = payload.since.date() if payload.since is not None else None
    bars = fetch_daily_bars(
        payload.ticker,
        since=since,
        alpha_vantage_key=settings.alpha_vantage_key,
    )
    try:
        run_massive_shadow(
            payload.ticker,
            bars,
            since=since,
            settings=settings,
        )
    except (MassiveProviderError, MassiveSemanticError) as exc:
        logger.error("Massive shadow failed for %s: %s", payload.ticker, exc)
    return bars


def process_payload(payload: dict) -> str:
    event_type = payload.get("event_type")
    if event_type != EVENT_TYPE_MARKET_REFRESH_REQUESTED:
        logger.info("market ingest ignoring event_type=%s", event_type)
        return "ignored"
    event = parse_market_refresh_requested(payload)
    bars = fetch_bars_for_event(event)
    with Session(engine) as session:
        result = persist_market_refresh(session, event, bars)
        session.commit()
    return result


def main(argv: list[str] | None = None) -> int:
    return worker_main(
        description="Consume stockviz.market.v1 market.refresh.requested.",
        topic=MARKET_TOPIC,
        group_id=MARKET_INGEST_CONSUMER,
        argv=argv,
        process=process_payload,
    )


if __name__ == "__main__":
    sys.exit(main())
