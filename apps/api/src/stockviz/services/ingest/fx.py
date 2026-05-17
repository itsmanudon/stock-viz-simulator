"""Daily FX rate ingest.

Mirrors ``services/ingest/prices.py``: a yfinance-backed fetcher with an
injectable callable so tests don't reach the network. Rates are stored as
USD-per-1-unit-of-foreign-currency in ``fx_rates``; conversion code in
``services/trading/fx.py`` reads from here.

USD is implicit (Decimal(1)) and never written to the table.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import Session

from stockviz.models import FxRate

logger = logging.getLogger(__name__)

SOURCE_YFINANCE = "yfinance"


@dataclass(frozen=True, slots=True)
class FxRecord:
    currency: str
    date: date
    usd_rate: Decimal
    source: str


YFinanceFxFn = Callable[[str, date | None], Any]
"""(yahoo_fx_ticker, start_date) -> pandas.DataFrame indexed by date with a Close column."""


def _default_yfinance_fx(yahoo_ticker: str, start: date | None) -> Any:
    import yfinance as yf

    kwargs: dict[str, Any] = {"interval": "1d", "auto_adjust": False, "actions": False}
    if start is None:
        kwargs["period"] = "5y"
    else:
        kwargs["start"] = start.isoformat()
    return yf.Ticker(yahoo_ticker).history(**kwargs)


def fetch_yfinance_fx(
    currency: str,
    *,
    start: date | None = None,
    history_fn: YFinanceFxFn = _default_yfinance_fx,
) -> list[FxRecord]:
    """Return USD-per-unit daily rates for ``currency`` from yfinance.

    Uses Yahoo's ``{CCY}USD=X`` convention (e.g. ``EURUSD=X`` returns the
    number of USD that 1 EUR buys), which is exactly the shape we store.
    """

    if currency == "USD":
        return []

    yahoo_ticker = f"{currency}USD=X"
    df = history_fn(yahoo_ticker, start)
    if df is None or len(df) == 0:
        return []

    records: list[FxRecord] = []
    for raw_ts, row in df.iterrows():
        ts = raw_ts.to_pydatetime() if hasattr(raw_ts, "to_pydatetime") else raw_ts
        if hasattr(ts, "tzinfo") and ts.tzinfo is not None:
            ts = ts.replace(tzinfo=None)
        try:
            records.append(
                FxRecord(
                    currency=currency,
                    date=ts.date() if hasattr(ts, "date") else ts,
                    usd_rate=Decimal(str(row["Close"])),
                    source=SOURCE_YFINANCE,
                )
            )
        except (KeyError, ValueError, TypeError) as exc:
            logger.warning("yfinance_fx: skipping bad row for %s at %s: %s", currency, ts, exc)
    return records


def upsert_fx_rates(session: Session, records: list[FxRecord]) -> int:
    """Idempotent insert into ``fx_rates``. Returns rows submitted."""
    if not records:
        return 0

    rows = [
        {
            "currency": r.currency,
            "date": r.date,
            "usd_rate": r.usd_rate,
            "source": r.source,
        }
        for r in records
    ]
    stmt = pg_insert(FxRate).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["currency", "date"],
        set_={"usd_rate": stmt.excluded.usd_rate, "source": stmt.excluded.source},
    )
    session.exec(stmt)  # type: ignore[arg-type]
    session.commit()
    return len(rows)


def ingest_fx(
    session: Session,
    currency: str,
    *,
    since: date | None = None,
) -> int:
    """Fetch + upsert. Returns bars written. USD is a no-op (0)."""
    if currency == "USD":
        return 0
    records = fetch_yfinance_fx(currency, start=since)
    if not records:
        logger.warning("ingest_fx: %s — no rates from yfinance", currency)
        return 0
    return upsert_fx_rates(session, records)
