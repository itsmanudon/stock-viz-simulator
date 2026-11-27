"""The forensic quality scorecard (A7.3, M5.1) and the financials switch (M5.2).

Pure functions over one company's annual facts, as known on a date
(``store.facts_as_of``): fiscal year ``t`` and the years before it. A figure
whose inputs are missing is **unknown**, with the missing fields named; it is
never guessed. Financial companies (banks, NBFCs, insurers: the ``Financial
Services`` sector) get no industrial model: the models were built on
non-financial firms and misread a lender's balance sheet.

- **Piotroski F-score** (Piotroski 2000), nine pass/fail tests, each pass 1:
  ROA > 0; operating cash flow > 0; ROA up; cash flow above net income
  (accruals); leverage (long-term debt / average total assets) down; current
  ratio up; no new shares; gross margin up; asset turnover (revenue /
  beginning assets) up. ROA is net income / beginning-of-year assets. The
  score is the passes among the tests that could be judged ("6 of 8 known").
  Without long-term debt, total debt stands in, and that test says so.
- **Altman Z''-score, emerging-market form** (Altman 2005): 3.25 + 6.56 X1 +
  3.26 X2 + 6.72 X3 + 1.05 X4, X1 = working capital / total assets, X2 =
  retained earnings / total assets, X3 = EBIT (operating income) / total
  assets, X4 = book equity / total liabilities. Zones: safe above 5.85, grey
  4.35-5.85, distress below 4.35.
- **Beneish M-score** (Beneish 1999, eight variables): -4.84 + 0.920 DSRI +
  0.528 GMI + 0.404 AQI + 0.892 SGI + 0.115 DEPI - 0.172 SGAI + 4.679 TATA -
  0.327 LVGI; flagged above -2.22 (the feature report's threshold; Beneish's
  own paper also cites -1.78). Variables as Beneish defined them, year t
  against t-1.
- **Cash flow to profit (CFO/PAT):** operating cash flow / net income, year t.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal

FINANCIAL_SECTORS = frozenset({"Financial Services", "Financials", "Banks", "Financial"})
ALTMAN_SAFE, ALTMAN_DISTRESS = 5.85, 4.35
BENEISH_FLAG = -2.22

Year = Mapping[str, Decimal | None]
"""One fiscal year's figures: concept key -> value (flows over the year,
stocks at its end)."""


@dataclass(frozen=True)
class Test:
    key: str
    label: str
    result: str  # pass | fail | unknown
    detail: str


@dataclass
class Piotroski:
    score: int
    known: int
    tests: list[Test] = field(default_factory=list)


@dataclass(frozen=True)
class Score:
    value: float | None
    zone: str | None
    missing: tuple[str, ...] = ()
    parts: tuple[tuple[str, float], ...] = ()


def is_financial(sector: str | None) -> bool:
    return (sector or "").strip() in FINANCIAL_SECTORS


def _f(year: Year | None, key: str) -> float | None:
    if year is None:
        return None
    value = year.get(key)
    return None if value is None else float(value)


def _div(a: float | None, b: float | None) -> float | None:
    if a is None or b is None or b == 0:
        return None
    return a / b


def _test(key: str, label: str, ok: bool | None, detail: str) -> Test:
    result = "unknown" if ok is None else ("pass" if ok else "fail")
    return Test(key, label, result, detail)


def piotroski(t: Year, t1: Year | None, t2: Year | None) -> Piotroski:
    """Year ``t`` with the two years before it (``t2`` only for last year's ROA)."""
    ni, ni1 = _f(t, "net_income"), _f(t1, "net_income")
    ta, ta1, ta2 = _f(t, "total_assets"), _f(t1, "total_assets"), _f(t2, "total_assets")
    roa, roa1 = _div(ni, ta1), _div(ni1, ta2)
    cfo = _f(t, "operating_cash_flow")
    debt_key = "long_term_debt" if _f(t, "long_term_debt") is not None else "total_debt"
    debt_note = "" if debt_key == "long_term_debt" else " (total debt: long-term debt not stored)"
    lev = _div(_f(t, debt_key), None if ta is None or ta1 is None else (ta + ta1) / 2)
    lev1 = _div(_f(t1, debt_key), None if ta1 is None or ta2 is None else (ta1 + ta2) / 2)
    if lev1 is None:  # two years of assets only: leverage against year-end assets
        lev, lev1 = _div(_f(t, debt_key), ta), _div(_f(t1, debt_key), ta1)
    cr, cr1 = (_div(_f(y, "current_assets"), _f(y, "current_liabilities")) for y in (t, t1))
    sh, sh1 = _f(t, "shares_outstanding"), _f(t1, "shares_outstanding")
    gm, gm1 = (_div(_f(y, "gross_profit"), _f(y, "revenue")) for y in (t, t1))
    at, at1 = _div(_f(t, "revenue"), ta1), _div(_f(t1, "revenue"), ta2)

    def gt(a: float | None, b: float | None) -> bool | None:
        return None if a is None or b is None else a > b

    tests = [
        _test("roa", "Return on assets above 0", None if roa is None else roa > 0,
              "net income / beginning-of-year assets"),
        _test("cfo", "Operating cash flow above 0", None if cfo is None else cfo > 0,
              "operating cash flow, year t"),
        _test("delta_roa", "Return on assets up", gt(roa, roa1), "ROA year t against t-1"),
        _test("accrual", "Cash flow above net income", gt(cfo, ni), "operating cash flow > net income"),
        _test("delta_leverage", "Leverage down", gt(lev1, lev),
              f"debt / average assets, t against t-1{debt_note}"),
        _test("delta_liquidity", "Current ratio up", gt(cr, cr1), "current assets / current liabilities"),
        _test("no_dilution", "No new shares", None if sh is None or sh1 is None else sh <= sh1,
              "shares outstanding, t against t-1"),
        _test("delta_margin", "Gross margin up", gt(gm, gm1), "gross profit / revenue"),
        _test("delta_turnover", "Asset turnover up", gt(at, at1), "revenue / beginning-of-year assets"),
    ]  # fmt: skip
    known = [x for x in tests if x.result != "unknown"]
    return Piotroski(
        score=sum(1 for x in known if x.result == "pass"), known=len(known), tests=tests
    )


def altman_z_em(t: Year) -> Score:
    need = ("current_assets", "current_liabilities", "total_assets", "retained_earnings",
            "operating_income", "equity", "total_liabilities")  # fmt: skip
    missing = tuple(k for k in need if _f(t, k) is None)
    ta = _f(t, "total_assets")
    if missing or not ta or not _f(t, "total_liabilities"):
        return Score(None, None, missing or ("total_assets",))
    x1 = ((_f(t, "current_assets") or 0) - (_f(t, "current_liabilities") or 0)) / ta
    x2 = (_f(t, "retained_earnings") or 0) / ta
    x3 = (_f(t, "operating_income") or 0) / ta
    x4 = (_f(t, "equity") or 0) / (_f(t, "total_liabilities") or 1)
    z = 3.25 + 6.56 * x1 + 3.26 * x2 + 6.72 * x3 + 1.05 * x4
    zone = "safe" if z > ALTMAN_SAFE else ("distress" if z < ALTMAN_DISTRESS else "grey")
    return Score(round(z, 3), zone, (),
                 (("x1", round(x1, 4)), ("x2", round(x2, 4)), ("x3", round(x3, 4)),
                  ("x4", round(x4, 4))))  # fmt: skip


def beneish_m(t: Year, t1: Year | None) -> Score:
    need = ("receivables", "revenue", "gross_profit", "current_assets", "net_ppe", "total_assets",
            "depreciation", "sga", "net_income", "operating_cash_flow", "current_liabilities")  # fmt: skip
    missing = tuple(sorted({k for k in need for y in (t, t1) if _f(y, k) is None}))
    if t1 is None or missing:
        return Score(None, None, missing or ("previous year",))

    def g(y: Year, k: str) -> float:
        return _f(y, k) or 0.0

    try:
        dsri = (g(t, "receivables") / g(t, "revenue")) / (g(t1, "receivables") / g(t1, "revenue"))
        gmi = (g(t1, "gross_profit") / g(t1, "revenue")) / (g(t, "gross_profit") / g(t, "revenue"))
        aqi = (1 - (g(t, "current_assets") + g(t, "net_ppe")) / g(t, "total_assets")) / (
            1 - (g(t1, "current_assets") + g(t1, "net_ppe")) / g(t1, "total_assets")
        )
        sgi = g(t, "revenue") / g(t1, "revenue")
        depi = (g(t1, "depreciation") / (g(t1, "depreciation") + g(t1, "net_ppe"))) / (
            g(t, "depreciation") / (g(t, "depreciation") + g(t, "net_ppe"))
        )
        sgai = (g(t, "sga") / g(t, "revenue")) / (g(t1, "sga") / g(t1, "revenue"))
        lt, lt1 = _f(t, "long_term_debt") or 0.0, _f(t1, "long_term_debt") or 0.0
        lvgi = ((g(t, "current_liabilities") + lt) / g(t, "total_assets")) / (
            (g(t1, "current_liabilities") + lt1) / g(t1, "total_assets")
        )
        tata = (g(t, "net_income") - g(t, "operating_cash_flow")) / g(t, "total_assets")
    except ZeroDivisionError:
        return Score(None, None, ("a zero denominator",))
    m = (-4.84 + 0.920 * dsri + 0.528 * gmi + 0.404 * aqi + 0.892 * sgi + 0.115 * depi
         - 0.172 * sgai + 4.679 * tata - 0.327 * lvgi)  # fmt: skip
    parts = (("dsri", dsri), ("gmi", gmi), ("aqi", aqi), ("sgi", sgi), ("depi", depi),
             ("sgai", sgai), ("tata", tata), ("lvgi", lvgi))  # fmt: skip
    return Score(round(m, 3), "flag" if m > BENEISH_FLAG else "clear", (),
                 tuple((k, round(v, 4)) for k, v in parts))  # fmt: skip


def cfo_to_pat(t: Year) -> Score:
    ratio = _div(_f(t, "operating_cash_flow"), _f(t, "net_income"))
    if ratio is None:
        return Score(None, None, ("operating_cash_flow", "net_income"))
    return Score(round(ratio, 3), "strong" if ratio >= 1 else "weak")
