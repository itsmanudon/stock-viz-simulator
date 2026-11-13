"""The fundamentals job (Phase 6.3): fetch, append point-in-time, report.

``yfinance`` runs for every active equity (indices and commodities skipped);
``edgar`` for US equities only, and only with ``SEC_USER_AGENT`` set. Each
symbol commits on its own, so one failure keeps the rest.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

from sqlmodel import Session, col, select

from stockviz.models import Symbol
from stockviz.models.instrument import Instrument
from stockviz.services.fundamentals import edgar_source, yfinance_source
from stockviz.services.fundamentals.store import FactRecord, record_facts
from stockviz.services.instruments import instrument_ids, instrument_of

logger = logging.getLogger(__name__)

YFINANCE_GAP_SECONDS = 1.0  # spread the statement requests out


@dataclass
class IngestReport:
    written: dict[str, int] = field(default_factory=dict)
    failed: dict[str, str] = field(default_factory=dict)


def equity_tickers(session: Session, *, country: str | None = None) -> list[str]:
    stmt = (
        select(Symbol.ticker)
        .join(Instrument, col(Instrument.id) == instrument_of(Symbol.ticker))
        .where(col(Symbol.is_active), col(Instrument.asset_type) == "equity")
    )
    if country is not None:
        stmt = stmt.where(col(Instrument.country) == country)
    return list(session.exec(stmt.order_by(col(Symbol.ticker))).all())


def ingest(
    session: Session,
    tickers: list[str],
    fetch: Callable[[str], list[FactRecord]],
    *,
    pause: float = 0.0,
) -> IngestReport:
    report = IngestReport()
    ids = instrument_ids(session, tickers)
    for ticker in tickers:
        instrument_id = ids.get(ticker)
        if instrument_id is None:
            report.failed[ticker] = "no instrument"
            continue
        try:
            records = fetch(ticker)
            report.written[ticker] = record_facts(session, instrument_id, records)
            session.commit()
        except Exception as exc:  # report and go on; the CLI exits 1
            session.rollback()
            report.failed[ticker] = str(exc)[:200]
            logger.warning("fundamentals: %s failed: %s", ticker, exc)
        if pause:
            time.sleep(pause)
    return report


def yfinance_fetcher(today: date) -> Callable[[str], list[FactRecord]]:
    return lambda ticker: yfinance_source.fetch_facts(ticker, today=today)


def edgar_fetcher(user_agent: str) -> Callable[[str], list[FactRecord]]:
    get = edgar_source.http_getter(user_agent)
    ciks = edgar_source.cik_map(get)
    return lambda ticker: edgar_source.fetch_facts(ticker, get=get, ciks=ciks)
