"""The macro series StockViz keeps, and the spreads built from them (A9.7).

Each series is a FRED id, grouped for the page. ``third_party`` marks series
FRED republishes from a copyright holder (ICE, CBOE, Moody's, S&P): fine for
the owner's personal research, but they must not be shown to other users
until the pre-release legal review has read their terms.

Spreads are differences of two stored series on the same date (the last value
of each on or before it, at most ``SPREAD_STALE_DAYS`` old), so a weekly and a
daily series still line up.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CatalogueSeries:
    series_id: str
    group: str
    label: str
    third_party: bool = False


@dataclass(frozen=True)
class Spread:
    key: str
    label: str
    a: str
    b: str
    units: str
    note: str


GROUPS: tuple[str, ...] = (
    "Rates",
    "Inflation",
    "Growth and labour",
    "Credit and stress",
    "Dollar and FX",
    "Commodities",
    "Money",
    "India",
)

CATALOGUE: tuple[CatalogueSeries, ...] = (
    CatalogueSeries("DFF", "Rates", "Effective federal funds rate"),
    CatalogueSeries("DGS3MO", "Rates", "US Treasury 3-month yield"),
    CatalogueSeries("DGS2", "Rates", "US Treasury 2-year yield"),
    CatalogueSeries("DGS10", "Rates", "US Treasury 10-year yield"),
    CatalogueSeries("DGS30", "Rates", "US Treasury 30-year yield"),
    CatalogueSeries("DFII10", "Rates", "US 10-year real yield (TIPS)"),
    CatalogueSeries("CPIAUCSL", "Inflation", "US CPI, all items"),
    CatalogueSeries("CPILFESL", "Inflation", "US core CPI (ex food and energy)"),
    CatalogueSeries("PCEPILFE", "Inflation", "US core PCE price index"),
    CatalogueSeries("T10YIE", "Inflation", "10-year breakeven inflation"),
    CatalogueSeries("UNRATE", "Growth and labour", "US unemployment rate"),
    CatalogueSeries("PAYEMS", "Growth and labour", "US nonfarm payrolls"),
    CatalogueSeries("ICSA", "Growth and labour", "US initial jobless claims"),
    CatalogueSeries("INDPRO", "Growth and labour", "US industrial production"),
    CatalogueSeries("GDPC1", "Growth and labour", "US real GDP"),
    CatalogueSeries("NFCI", "Credit and stress", "Chicago Fed financial conditions"),
    CatalogueSeries(
        "BAMLH0A0HYM2", "Credit and stress", "US high-yield OAS (ICE BofA)", third_party=True
    ),
    CatalogueSeries("BAA10Y", "Credit and stress", "Moody's Baa minus 10-year", third_party=True),
    CatalogueSeries("VIXCLS", "Credit and stress", "CBOE VIX", third_party=True),
    CatalogueSeries("DTWEXBGS", "Dollar and FX", "Broad US dollar index"),
    CatalogueSeries("DEXINUS", "Dollar and FX", "Indian rupees per US dollar"),
    CatalogueSeries("DCOILWTICO", "Commodities", "WTI crude oil"),
    CatalogueSeries("DCOILBRENTEU", "Commodities", "Brent crude oil"),
    CatalogueSeries("DHHNGSP", "Commodities", "Henry Hub natural gas"),
    CatalogueSeries("M2SL", "Money", "US M2 money stock"),
    CatalogueSeries("INDIRLTLT01STM", "India", "India 10-year government bond yield (OECD)"),
    CatalogueSeries("IRSTCI01INM156N", "India", "India call money rate (OECD)"),
    CatalogueSeries("FPCPITOTLZGIND", "India", "India CPI inflation, annual (World Bank)"),
)

SPREADS: tuple[Spread, ...] = (
    Spread(
        "us_10y_2y",
        "10-year minus 2-year",
        "DGS10",
        "DGS2",
        "percentage points",
        "Below zero, the curve is inverted.",
    ),
    Spread(
        "us_10y_3m",
        "10-year minus 3-month",
        "DGS10",
        "DGS3MO",
        "percentage points",
        "The curve the New York Fed's recession model reads.",
    ),
    Spread(
        "brent_wti",
        "Brent minus WTI",
        "DCOILBRENTEU",
        "DCOILWTICO",
        "dollars a barrel",
        "The gap between the seaborne and the US inland crude benchmarks.",
    ),
    Spread(
        "fed_funds_vs_10y",
        "10-year minus fed funds",
        "DGS10",
        "DFF",
        "percentage points",
        "How far long rates sit above the policy rate.",
    ),
    Spread(
        "india_us_10y",
        "India 10-year minus US 10-year",
        "INDIRLTLT01STM",
        "DGS10",
        "percentage points",
        "India's monthly average yield against the US daily yield on the month's first date.",
    ),
)

SPREAD_STALE_DAYS = 7

BY_ID: dict[str, CatalogueSeries] = {s.series_id: s for s in CATALOGUE}
