"""Symbol metadata backfill (sector, exchange).

The seed step only knows ticker + name; sector and exchange come from
yfinance's ``Ticker.info`` payload, which is a *very* loose dict (every
ticker returns slightly different keys). We pull the few fields the UI
needs and ignore the rest.

Idempotent: missing/None values leave the column alone, so re-running
doesn't blow away curated overrides.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from sqlmodel import Session, select

from stockviz.models import Symbol

logger = logging.getLogger(__name__)

InfoFetchFn = Callable[[str], dict[str, Any]]
"""(ticker) -> yfinance Ticker.info dict."""


def _default_info_fetch(ticker: str) -> dict[str, Any]:
    import yfinance as yf

    return dict(yf.Ticker(ticker).info or {})


def _pick(info: dict[str, Any], *keys: str) -> str | None:
    for k in keys:
        v = info.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def backfill_symbol_metadata(
    session: Session,
    *,
    fetch_fn: InfoFetchFn = _default_info_fetch,
    only: list[str] | None = None,
) -> dict[str, str]:
    """Fill in ``sector`` and ``exchange`` for symbols missing them.

    Returns a ``{ticker: status}`` map where status is one of
    ``"updated" / "skipped" / "failed"``. Skipped means yfinance didn't have
    usable info for that ticker; failed means a network/parse error.
    """

    stmt = select(Symbol)
    if only:
        stmt = stmt.where(Symbol.ticker.in_(only))  # type: ignore[attr-defined]
    symbols = list(session.exec(stmt).all())

    out: dict[str, str] = {}
    for symbol in symbols:
        if symbol.sector and symbol.exchange:
            out[symbol.ticker] = "skipped"
            continue
        try:
            info = fetch_fn(symbol.ticker)
        except Exception as exc:
            logger.warning("metadata: %s yfinance.info failed: %s", symbol.ticker, exc)
            out[symbol.ticker] = "failed"
            continue

        sector = symbol.sector or _pick(info, "sector", "industryDisp")
        exchange = symbol.exchange or _pick(info, "exchange", "fullExchangeName")

        if not sector and not exchange:
            out[symbol.ticker] = "skipped"
            continue

        if sector:
            symbol.sector = sector
        if exchange:
            symbol.exchange = exchange
        session.add(symbol)
        out[symbol.ticker] = "updated"

    session.commit()
    return out
