"""On-demand history snapshots from an optional provider (Phase 4.7).

A paid provider is used for a one-off (or monthly) pull of full history, not
nightly. ``snapshot`` fetches, compares with what is stored, and writes only
when asked. Written bars go through ``upsert_bars`` (screening, pence, the
source rank), so a later nightly yfinance refresh adds newer days and never
replaces them.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlmodel import Session, col, select

from stockviz.models import PriceBar, Symbol
from stockviz.models.instrument import InstrumentIdentifier
from stockviz.services.ingest.prices import DAILY_INTERVAL, BarRecord, upsert_bars
from stockviz.services.instruments import instrument_ids, instrument_of


@dataclass
class TickerReport:
    ticker: str
    fetched: int = 0
    new_days: int = 0
    overlap: int = 0
    max_close_diff_pct: Decimal | None = None
    written: int = 0
    error: str | None = None


def indian_tickers(session: Session) -> list[str]:
    rows = session.exec(
        select(Symbol.ticker).where(col(Symbol.is_active).is_(True)).order_by(col(Symbol.ticker))
    ).all()
    return [t for t in rows if t.upper().endswith((".NS", ".BO"))]


def compare(session: Session, ticker: str, bars: list[BarRecord]) -> TickerReport:
    stored = {
        ts.date(): close
        for ts, close in session.exec(
            select(col(PriceBar.ts), col(PriceBar.close)).where(
                col(PriceBar.instrument_id) == instrument_of(ticker),
                col(PriceBar.interval) == DAILY_INTERVAL,
            )
        ).all()
    }
    report = TickerReport(ticker=ticker, fetched=len(bars))
    worst: Decimal | None = None
    for bar in bars:
        old = stored.get(bar.ts.date())
        if old is None:
            report.new_days += 1
            continue
        report.overlap += 1
        if old:
            diff = abs(bar.close - old) / old * 100
            worst = diff if worst is None else max(worst, diff)
    report.max_close_diff_pct = worst.quantize(Decimal("0.01")) if worst is not None else None
    return report


def record_identifier(session: Session, ticker: str, scheme: str, value: str) -> None:
    """Add the provider's own id for the instrument (e.g. scheme ``kite``) once."""
    instrument_id = instrument_ids(session, [ticker]).get(ticker)
    if instrument_id is None:
        return
    exists = session.exec(
        select(InstrumentIdentifier.id).where(
            col(InstrumentIdentifier.instrument_id) == instrument_id,
            col(InstrumentIdentifier.scheme) == scheme,
            col(InstrumentIdentifier.valid_to).is_(None),
        )
    ).first()
    if exists is None:
        session.add(
            InstrumentIdentifier(
                instrument_id=instrument_id,
                scheme=scheme,
                value=value,
                valid_from=date.today(),
            )
        )


def snapshot(
    session: Session,
    tickers: list[str],
    fetch: Callable[[str], tuple[list[BarRecord], str | None]],
    *,
    scheme: str,
    apply: bool,
) -> list[TickerReport]:
    """``fetch(ticker) -> (bars, provider id)``; write only when ``apply``.

    Each ticker commits on its own, so one failure keeps the others.
    """
    reports: list[TickerReport] = []
    for ticker in tickers:
        try:
            bars, provider_id = fetch(ticker)
        except Exception as exc:  # report and go on; the CLI exits 1
            reports.append(TickerReport(ticker=ticker, error=str(exc)[:200]))
            continue
        report = compare(session, ticker, bars)
        if apply and bars:
            report.written = upsert_bars(session, bars)
            if provider_id is not None:
                record_identifier(session, ticker, scheme, provider_id)
            session.commit()
        reports.append(report)
    return reports
