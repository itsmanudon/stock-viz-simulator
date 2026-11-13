"""Valuation and company metrics as of a date (Phase 6.4).

Everything is computed from what was known on the date: the point-in-time
facts (``facts_as_of``) and that day's close. When the listing trades in one
currency and the company reports in another (INFY.NS trades in INR and
reports in USD), the price is converted at that day's FX rate before it meets
the statements.

- **TTM** flows are the sum of the last four quarters when they are
  consecutive (each about three months after the last, spanning a year);
  otherwise the latest annual figure is used and ``basis`` says so.
- **Stock** values (equity, cash, debt, shares) are the latest balance-sheet
  date on or before the date.
- A metric whose inputs are missing, or meaningless (a P/E on a loss), is
  ``None`` with the reason. Nothing is reported as 0.
- **ROIC** here is pre-tax: operating income over (equity + debt - cash),
  because no tax rate is stored. Its label says so.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from itertools import pairwise

from sqlmodel import Session, col, select

from stockviz.models import PriceBar, Symbol
from stockviz.models.fundamentals import FundamentalFact
from stockviz.services.fundamentals.store import facts_as_of
from stockviz.services.instruments import instrument_ids, instrument_of
from stockviz.services.trading.fx import latest_rate


@dataclass
class Metric:
    key: str
    label: str
    value: float | None
    unit: str  # "x", "%", or a currency
    reason: str | None = None


@dataclass
class Valuation:
    ticker: str
    as_of: date
    price: Decimal | None = None
    price_date: date | None = None
    trading_currency: str = "USD"
    reporting_currency: str | None = None
    fx_rate: Decimal | None = None  # reporting units per trading unit
    basis: str | None = None  # "ttm" | "annual"
    point_in_time: bool = False
    sources: list[str] = field(default_factory=list)
    metrics: list[Metric] = field(default_factory=list)

    def value(self, key: str) -> float | None:
        return next((m.value for m in self.metrics if m.key == key), None)


Known = dict[tuple[str, str, date], FundamentalFact]


def _flows(known: Known, concept: str, period_type: str) -> list[FundamentalFact]:
    return sorted(
        (f for (c, p, _e), f in known.items() if c == concept and p == period_type),
        key=lambda f: f.period_end,
        reverse=True,
    )


def ttm(known: Known, concept: str) -> tuple[Decimal | None, str | None, list[FundamentalFact]]:
    """(value, basis, facts used): four consecutive quarters, else the latest year."""
    quarters = _flows(known, concept, "quarter")[:4]
    if len(quarters) == 4:
        gaps = [(a.period_end - b.period_end).days for a, b in pairwise(quarters)]
        if all(80 <= g <= 100 for g in gaps):
            return sum((q.value for q in quarters), Decimal(0)), "ttm", quarters
    annual = _flows(known, concept, "annual")
    if annual:
        return annual[0].value, "annual", annual[:1]
    return None, None, []


def latest_stock(known: Known, concept: str) -> FundamentalFact | None:
    rows = _flows(known, concept, "instant")
    return rows[0] if rows else None


def _close_on(session: Session, ticker: str, day: date) -> tuple[Decimal | None, date | None]:
    bar = session.exec(
        select(PriceBar)
        .where(
            col(PriceBar.instrument_id) == instrument_of(ticker),
            col(PriceBar.interval) == "1d",
            col(PriceBar.ts) <= datetime.combine(day, time.max),
        )
        .order_by(col(PriceBar.ts).desc())
        .limit(1)
    ).first()
    return (bar.close, bar.ts.date()) if bar else (None, None)


def _ratio(num: Decimal | None, den: Decimal | None, *, positive_den: bool = False) -> float | None:
    if num is None or den is None or den == 0 or (positive_den and den < 0):
        return None
    return float(num / den)


def valuation(session: Session, ticker: str, as_of: date) -> Valuation:
    ticker = ticker.upper()
    symbol = session.get(Symbol, ticker)
    out = Valuation(
        ticker=ticker, as_of=as_of, trading_currency=(symbol.currency if symbol else None) or "USD"
    )
    instrument_id = instrument_ids(session, [ticker]).get(ticker)
    known: Known = facts_as_of(session, instrument_id, as_of) if instrument_id is not None else {}
    out.price, out.price_date = _close_on(session, ticker, as_of)

    revenue, basis, used_rev = ttm(known, "revenue")
    net_income, _b, used_ni = ttm(known, "net_income")
    gross, _b, _u = ttm(known, "gross_profit")
    op_income, _b, _u = ttm(known, "operating_income")
    ebitda, _b, _u = ttm(known, "ebitda")
    ocf, _b, _u = ttm(known, "operating_cash_flow")
    capex, _b, _u = ttm(known, "capex")
    fcf, _b, _u = ttm(known, "free_cash_flow")
    if fcf is None and ocf is not None and capex is not None:
        fcf = ocf - capex
    dividends, _b, _u = ttm(known, "dividends_paid")
    out.basis = basis

    equity = latest_stock(known, "equity")
    cash = latest_stock(known, "cash")
    debt = latest_stock(known, "total_debt")
    assets = latest_stock(known, "total_assets")
    cur_assets = latest_stock(known, "current_assets")
    cur_liab = latest_stock(known, "current_liabilities")
    shares = latest_stock(known, "shares_outstanding")

    used = [f for f in (*used_rev, *used_ni, equity, cash, debt, assets, shares) if f is not None]
    currencies = {f.currency for f in used if f.currency}
    out.reporting_currency = currencies.pop() if len(currencies) == 1 else None
    out.sources = sorted({f.source for f in used})
    out.point_in_time = bool(used) and all(f.point_in_time for f in used)

    # Price in the reporting currency.
    price_rep: Decimal | None = None
    if out.price is not None and out.reporting_currency:
        if out.reporting_currency == out.trading_currency:
            out.fx_rate = Decimal(1)
        else:
            try:
                usd_trading = latest_rate(session, out.trading_currency, on_or_before=as_of)
                usd_reporting = latest_rate(session, out.reporting_currency, on_or_before=as_of)
                out.fx_rate = usd_trading / usd_reporting
            except LookupError:
                out.fx_rate = None
        if out.fx_rate is not None:
            price_rep = out.price * out.fx_rate

    shares_n = shares.value if shares else None
    mcap = price_rep * shares_n if price_rep is not None and shares_n else None
    ev = None
    if mcap is not None:
        ev = mcap + (debt.value if debt else Decimal(0)) - (cash.value if cash else Decimal(0))

    cur = out.reporting_currency or "?"
    missing_price = "no close or FX rate" if price_rep is None else None
    missing_shares = "no shares outstanding" if not shares_n else None

    def m(key, label, value, unit="x", reason=None):
        out.metrics.append(Metric(key, label, value, unit, reason if value is None else None))

    def why(*parts: str | None) -> str:
        return next((p for p in parts if p), "inputs missing")

    m(
        "market_cap",
        "Market cap",
        float(mcap) if mcap is not None else None,
        cur,
        why(missing_price, missing_shares),
    )
    m(
        "enterprise_value",
        "Enterprise value",
        float(ev) if ev is not None else None,
        cur,
        why(missing_price, missing_shares),
    )
    pe = _ratio(mcap, net_income, positive_den=True)
    m(
        "pe",
        "P/E",
        pe,
        reason="loss"
        if net_income is not None and net_income < 0
        else why(missing_price, missing_shares, "no net income"),
    )
    m(
        "pb",
        "P/B",
        _ratio(mcap, equity.value if equity else None, positive_den=True),
        reason=why(missing_price, missing_shares, "no equity" if not equity else "negative equity"),
    )
    m(
        "ps",
        "P/S",
        _ratio(mcap, revenue, positive_den=True),
        reason=why(missing_price, missing_shares, "no revenue"),
    )
    m(
        "ev_ebitda",
        "EV/EBITDA",
        _ratio(ev, ebitda, positive_den=True),
        reason=why(missing_price, missing_shares, "no EBITDA"),
    )
    m(
        "ev_revenue",
        "EV/Revenue",
        _ratio(ev, revenue, positive_den=True),
        reason=why(missing_price, missing_shares, "no revenue"),
    )
    m(
        "p_fcf",
        "Price/FCF",
        _ratio(mcap, fcf, positive_den=True),
        reason=why(missing_price, missing_shares, "no free cash flow"),
    )
    dy = _ratio(dividends, mcap)
    m(
        "dividend_yield",
        "Dividend yield",
        dy * 100 if dy is not None else None,
        "%",
        why(missing_price, missing_shares, "no dividends reported"),
    )

    def pct(num, den):
        r = _ratio(num, den, positive_den=True)
        return r * 100 if r is not None else None

    m("gross_margin", "Gross margin", pct(gross, revenue), "%", "no gross profit")
    m("operating_margin", "Operating margin", pct(op_income, revenue), "%", "no operating income")
    m("net_margin", "Net margin", pct(net_income, revenue), "%", "no net income")
    m(
        "roe",
        "Return on equity",
        pct(net_income, equity.value if equity else None),
        "%",
        "no equity",
    )
    m(
        "roa",
        "Return on assets",
        pct(net_income, assets.value if assets else None),
        "%",
        "no assets",
    )
    invested = None
    if equity is not None and debt is not None:
        invested = equity.value + debt.value - (cash.value if cash else Decimal(0))
    m(
        "roic_pretax",
        "Return on invested capital (pre-tax)",
        pct(op_income, invested),
        "%",
        "no equity or debt",
    )
    m(
        "debt_to_equity",
        "Debt to equity",
        _ratio(debt.value if debt else None, equity.value if equity else None, positive_den=True),
        reason="no debt or equity",
    )
    m(
        "current_ratio",
        "Current ratio",
        _ratio(
            cur_assets.value if cur_assets else None,
            cur_liab.value if cur_liab else None,
            positive_den=True,
        ),
        reason="no current assets or liabilities",
    )
    m("payout_ratio", "Payout ratio", pct(dividends, net_income), "%", "no dividends or net income")

    # Growth: TTM now against TTM as known a year earlier.
    if instrument_id is not None:
        year_ago = facts_as_of(session, instrument_id, as_of - timedelta(days=365))
        for key, label, now in (
            ("revenue", "Revenue growth", revenue),
            ("net_income", "Earnings growth", net_income),
        ):
            then, _b, _u = ttm(year_ago, key)
            g = _ratio(
                now - then if now is not None and then is not None else None,
                then,
                positive_den=True,
            )
            m(
                f"{key}_growth",
                f"{label} (year on year)",
                g * 100 if g is not None else None,
                "%",
                "no figure a year earlier",
            )
    return out


def history(
    session: Session, ticker: str, key: str, *, end: date, years: int = 5
) -> tuple[list[tuple[date, float]], float | None]:
    """Month-end values of one metric over ``years``, and the latest's percentile."""
    points: list[tuple[date, float]] = []
    month = date(end.year - years, end.month, 1)
    while month <= end:
        nxt = date(month.year + (month.month == 12), month.month % 12 + 1, 1)
        day = min(nxt - timedelta(days=1), end)
        value = valuation(session, ticker, day).value(key)
        if value is not None:
            points.append((day, value))
        month = nxt
    if len(points) < 2:
        return points, None
    latest = points[-1][1]
    below = sum(1 for _d, v in points if v <= latest)
    return points, below / len(points) * 100
