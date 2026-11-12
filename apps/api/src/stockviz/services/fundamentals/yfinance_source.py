"""Fundamentals from yfinance statements (Phase 6.3, the stopgap source).

yfinance gives statement tables (rows are line items, columns are period-end
dates) with no filing dates, so every figure is dated by the day it was
fetched and marked ``point_in_time = False``. Balance-sheet columns are
instants; income and cash-flow columns are annual or quarterly periods.
Reporting currency comes from ``info["financialCurrency"]``.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from datetime import date
from decimal import Decimal
from typing import Any

from stockviz.services.fundamentals.concepts import CONCEPTS, YFINANCE, unit_for
from stockviz.services.fundamentals.store import FactRecord

SOURCE = "yfinance"

# (attribute on yfinance.Ticker, period type for flows)
STATEMENTS = (
    ("income_stmt", "annual"),
    ("quarterly_income_stmt", "quarter"),
    ("cashflow", "annual"),
    ("quarterly_cashflow", "quarter"),
    ("balance_sheet", "annual"),
    ("quarterly_balance_sheet", "quarter"),
)


def _default_ticker(symbol: str) -> Any:
    import yfinance as yf

    return yf.Ticker(symbol)


def fetch_facts(
    symbol: str,
    *,
    today: date,
    ticker_factory: Callable[[str], Any] = _default_ticker,
) -> list[FactRecord]:
    ticker = ticker_factory(symbol)
    try:
        currency = (ticker.info or {}).get("financialCurrency")
    except Exception:  # info is best effort; statements still carry values
        currency = None
    out: list[FactRecord] = []
    for attr, flow_period in STATEMENTS:
        frame = getattr(ticker, attr, None)
        if frame is None or getattr(frame, "empty", True):
            continue
        for row_name, concept_key in YFINANCE.items():
            if row_name not in frame.index:
                continue
            concept = CONCEPTS[concept_key]
            for column, raw in frame.loc[row_name].items():
                if raw is None or (isinstance(raw, float) and math.isnan(raw)):
                    continue
                value = Decimal(str(raw))
                if concept.outflow:
                    value = abs(value)
                period_end = column.date() if hasattr(column, "date") else column
                out.append(
                    FactRecord(
                        concept=concept_key,
                        period_type="instant" if concept.kind == "stock" else flow_period,
                        period_end=period_end,
                        value=value,
                        unit=unit_for(concept, currency),
                        currency=currency if concept.unit != "shares" else None,
                        available_at=today,
                        point_in_time=False,
                        source=SOURCE,
                        source_concept=f"yfinance:{attr}:{row_name}",
                    )
                )
    return out
