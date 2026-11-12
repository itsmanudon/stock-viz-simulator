"""Normalised line items and how each source names them (Phase 6.3).

A concept is ``(key, kind, unit)``: ``kind`` is ``flow`` (over a period:
income and cash-flow lines) or ``stock`` (at a date: balance-sheet lines);
``unit`` is ``money``, ``per_share`` or ``shares``. Sources map their own
names onto these keys; an unmapped name is ignored, never guessed. Signs are
normalised so outflows (capital expenditure, dividends paid) are positive.

The mapping is versioned (``MAPPING_VERSION``); change it by adding a version,
so stored facts keep the meaning they were written with.
"""

from __future__ import annotations

from typing import Literal, NamedTuple

MAPPING_VERSION = "v1"

Kind = Literal["flow", "stock"]
Unit = Literal["money", "per_share", "shares"]


class Concept(NamedTuple):
    key: str
    kind: Kind
    unit: Unit
    label: str
    outflow: bool = False  # stored as a positive amount


CONCEPTS: dict[str, Concept] = {
    c.key: c
    for c in (
        Concept("revenue", "flow", "money", "Revenue"),
        Concept("gross_profit", "flow", "money", "Gross profit"),
        Concept("operating_income", "flow", "money", "Operating income"),
        Concept("ebitda", "flow", "money", "EBITDA"),
        Concept("net_income", "flow", "money", "Net income"),
        Concept("eps_basic", "flow", "per_share", "EPS (basic)"),
        Concept("eps_diluted", "flow", "per_share", "EPS (diluted)"),
        Concept("shares_diluted_avg", "flow", "shares", "Diluted average shares"),
        Concept("operating_cash_flow", "flow", "money", "Operating cash flow"),
        Concept("capex", "flow", "money", "Capital expenditure", outflow=True),
        Concept("free_cash_flow", "flow", "money", "Free cash flow"),
        Concept("dividends_paid", "flow", "money", "Dividends paid", outflow=True),
        Concept("total_assets", "stock", "money", "Total assets"),
        Concept("total_liabilities", "stock", "money", "Total liabilities"),
        Concept("equity", "stock", "money", "Shareholders' equity"),
        Concept("cash", "stock", "money", "Cash and equivalents"),
        Concept("total_debt", "stock", "money", "Total debt"),
        Concept("current_assets", "stock", "money", "Current assets"),
        Concept("current_liabilities", "stock", "money", "Current liabilities"),
        Concept("shares_outstanding", "stock", "shares", "Shares outstanding"),
    )
}

# yfinance statement row names (Ticker.income_stmt / balance_sheet / cashflow).
YFINANCE: dict[str, str] = {
    "Total Revenue": "revenue",
    "Gross Profit": "gross_profit",
    "Operating Income": "operating_income",
    "EBITDA": "ebitda",
    "Net Income": "net_income",
    "Basic EPS": "eps_basic",
    "Diluted EPS": "eps_diluted",
    "Diluted Average Shares": "shares_diluted_avg",
    "Operating Cash Flow": "operating_cash_flow",
    "Capital Expenditure": "capex",
    "Free Cash Flow": "free_cash_flow",
    "Cash Dividends Paid": "dividends_paid",
    "Total Assets": "total_assets",
    "Total Liabilities Net Minority Interest": "total_liabilities",
    "Stockholders Equity": "equity",
    "Cash And Cash Equivalents": "cash",
    "Total Debt": "total_debt",
    "Current Assets": "current_assets",
    "Current Liabilities": "current_liabilities",
    "Ordinary Shares Number": "shares_outstanding",
}

# EDGAR XBRL tags (us-gaap, dei), in order of preference per concept: the
# first tag with a value for a period wins.
EDGAR: dict[str, tuple[str, ...]] = {
    "revenue": (
        "us-gaap:Revenues",
        "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
        "us-gaap:SalesRevenueNet",
    ),
    "gross_profit": ("us-gaap:GrossProfit",),
    "operating_income": ("us-gaap:OperatingIncomeLoss",),
    "net_income": ("us-gaap:NetIncomeLoss",),
    "eps_basic": ("us-gaap:EarningsPerShareBasic",),
    "eps_diluted": ("us-gaap:EarningsPerShareDiluted",),
    "shares_diluted_avg": ("us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding",),
    "operating_cash_flow": ("us-gaap:NetCashProvidedByUsedInOperatingActivities",),
    "capex": ("us-gaap:PaymentsToAcquirePropertyPlantAndEquipment",),
    "dividends_paid": ("us-gaap:PaymentsOfDividends", "us-gaap:PaymentsOfDividendsCommonStock"),
    "total_assets": ("us-gaap:Assets",),
    "total_liabilities": ("us-gaap:Liabilities",),
    "equity": ("us-gaap:StockholdersEquity",),
    "cash": ("us-gaap:CashAndCashEquivalentsAtCarryingValue",),
    "total_debt": ("us-gaap:LongTermDebt", "us-gaap:DebtCurrent"),
    "current_assets": ("us-gaap:AssetsCurrent",),
    "current_liabilities": ("us-gaap:LiabilitiesCurrent",),
    "shares_outstanding": ("dei:EntityCommonStockSharesOutstanding",),
}


def unit_for(concept: Concept, currency: str | None) -> str:
    if concept.unit == "shares":
        return "shares"
    if concept.unit == "per_share":
        return f"{currency or '?'}/share"
    return currency or "?"
