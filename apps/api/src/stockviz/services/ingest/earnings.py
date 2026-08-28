"""Earnings-calendar ingestion from yfinance.

This is an operator-triggered provider path (``stockviz earnings``), not a
request-time network call. Every write is idempotent on ticker/date/fiscal
period so the command can safely be rerun as estimates become actuals.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date as date_type
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlmodel import Session, select

from stockviz._time import utcnow
from stockviz.models import EarningsEvent, Symbol

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class EarningsRecord:
    ticker: str
    event_date: date_type
    report_time: str | None
    fiscal_period: str
    eps_estimate: Decimal | None
    eps_actual: Decimal | None
    surprise_pct: Decimal | None
    source: str = "yfinance"


EarningsFetchFn = Callable[[str], Any]


def _default_earnings_fetch(ticker: str) -> Any:
    import yfinance as yf

    return yf.Ticker(ticker).get_earnings_dates(limit=16)


def _number(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        if isinstance(value, float) and math.isnan(value):
            return None
        result = Decimal(str(value))
        return result if result.is_finite() else None
    except (InvalidOperation, TypeError, ValueError):
        return None


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"nan", "nat", "none"}:
        return None
    return text


def _event_date(value: Any) -> date_type | None:
    if value is None:
        return None
    if hasattr(value, "to_pydatetime"):
        value = value.to_pydatetime()
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date_type):
        return value
    try:
        return date_type.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _row_value(row: Any, *names: str) -> Any:
    for name in names:
        try:
            result = row.get(name) if hasattr(row, "get") else row[name]
        except (KeyError, TypeError):
            result = None
        if result is not None:
            return result
    return None


def parse_earnings_rows(ticker: str, rows: Any) -> list[EarningsRecord]:
    """Normalize yfinance's DataFrame-like result without importing pandas."""
    if rows is None or getattr(rows, "empty", False):
        return []
    records: list[EarningsRecord] = []
    try:
        iterator = rows.iterrows()
    except AttributeError:
        return records
    for raw_date, row in iterator:
        event_date = _event_date(raw_date)
        if event_date is None:
            continue
        records.append(
            EarningsRecord(
                ticker=ticker.upper(),
                event_date=event_date,
                report_time=_text(_row_value(row, "When", "Report Time", "reportTime")),
                fiscal_period=_text(_row_value(row, "Event", "Fiscal Period", "fiscalPeriod"))
                or "",
                eps_estimate=_number(_row_value(row, "EPS Estimate", "EPS Estimate ($)")),
                eps_actual=_number(_row_value(row, "Reported EPS", "Reported EPS ($)")),
                surprise_pct=_number(_row_value(row, "Surprise(%)", "Surprise (%)", "Surprise")),
            )
        )
    return records


def ingest_earnings_for_ticker(
    session: Session,
    ticker: str,
    *,
    fetch_fn: EarningsFetchFn = _default_earnings_fetch,
) -> int:
    ticker = ticker.upper()
    if session.get(Symbol, ticker) is None:
        logger.warning("ingest_earnings: unknown ticker %s, skipping", ticker)
        return 0
    try:
        records = parse_earnings_rows(ticker, fetch_fn(ticker))
    except Exception as exc:
        logger.warning("ingest_earnings: %s provider failed: %s", ticker, exc)
        return 0

    fetched_at = utcnow()
    written = 0
    for record in records:
        existing = session.exec(
            select(EarningsEvent).where(
                EarningsEvent.ticker == ticker,
                EarningsEvent.event_date == record.event_date,
                EarningsEvent.fiscal_period == record.fiscal_period,
            )
        ).first()
        values = {
            "report_time": record.report_time,
            "eps_estimate": record.eps_estimate,
            "eps_actual": record.eps_actual,
            "surprise_pct": record.surprise_pct,
            "source": record.source,
        }
        if existing is None:
            session.add(
                EarningsEvent(
                    ticker=ticker,
                    event_date=record.event_date,
                    fiscal_period=record.fiscal_period,
                    fetched_at=fetched_at,
                    **values,
                )
            )
            written += 1
        elif any(getattr(existing, key) != value for key, value in values.items()):
            for key, value in values.items():
                setattr(existing, key, value)
            existing.fetched_at = fetched_at
            written += 1
    session.commit()
    return written


def ingest_earnings_for_all(
    session: Session,
    *,
    fetch_fn: EarningsFetchFn = _default_earnings_fetch,
    only: list[str] | None = None,
) -> dict[str, int]:
    stmt = select(Symbol.ticker).where(Symbol.is_active)  # type: ignore[arg-type]
    if only:
        stmt = stmt.where(Symbol.ticker.in_([ticker.upper() for ticker in only]))  # type: ignore[attr-defined]
    results: dict[str, int] = {}
    for ticker in session.exec(stmt).all():
        results[ticker] = ingest_earnings_for_ticker(session, ticker, fetch_fn=fetch_fn)
    return results
