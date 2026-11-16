"""Stress tests on today's holdings (Phase 8.4).

Every scenario is applied **instantly** to today's book, in the base
currency: a stock moves by the scenario's local return and its currency by
the scenario's currency move; foreign cash moves with its currency; open
options are repriced in full with Black-Scholes at the moved spot with
today's volatility and time to expiry.

- **Historical replays** use each holding's own move over a past window
  (close on the last stored bar on or before each end of the window), and
  that window's currency move. A holding with no bar at the window's start
  takes its market index's move times its beta to that index over the last
  two years (500 sessions), and is reported as proxied. With no index
  history either, it is reported as missing and left unmoved.
- **Hypothetical shocks** move every US-listed or Indian-listed stock by a
  fixed amount, or the rupee against the dollar.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlmodel import Session, col, select

from stockviz._time import utcnow
from stockviz.models import OptionsPosition, OptionStatus, Portfolio, PriceBar
from stockviz.models.market import FxRate
from stockviz.services.instruments import instrument_of
from stockviz.services.options.pricing import black_scholes, historical_volatility
from stockviz.services.options.trade import RISK_FREE_RATE
from stockviz.services.risk.scenarios import proxy_for
from stockviz.services.trading.exposure import classifications
from stockviz.services.trading.fx import convert as fx_convert
from stockviz.services.trading.portfolio import PortfolioValuation

STRESS_METHOD = "instant_revaluation"
BETA_SESSIONS = 500


@dataclass(frozen=True, slots=True)
class HistoricalWindow:
    key: str
    name: str
    start: date
    end: date


HISTORICAL: tuple[HistoricalWindow, ...] = (
    HistoricalWindow("gfc_2008", "2008 financial crisis", date(2008, 9, 12), date(2009, 3, 9)),
    HistoricalWindow("covid_2020", "COVID crash", date(2020, 2, 19), date(2020, 3, 23)),
    HistoricalWindow("rates_2022", "2022 rate shock", date(2022, 1, 3), date(2022, 10, 12)),
    HistoricalWindow(
        "taper_2013", "2013 taper tantrum (rupee fall)", date(2013, 5, 22), date(2013, 8, 28)
    ),
)


@dataclass(frozen=True, slots=True)
class Shock:
    key: str
    name: str
    us: float = 0.0
    india: float = 0.0
    rupee: float = 0.0
    """Change in USD per rupee: -0.10 is the rupee 10% weaker."""


HYPOTHETICAL: tuple[Shock, ...] = (
    Shock("us_minus_10", "US stocks -10%", us=-0.10),
    Shock("us_minus_20", "US stocks -20%", us=-0.20),
    Shock("india_minus_10", "Indian stocks -10%", india=-0.10),
    Shock("india_minus_20", "Indian stocks -20%", india=-0.20),
    Shock("rupee_minus_10", "Rupee 10% weaker against the dollar", rupee=-0.10),
    Shock("combined", "US -20%, India -20%, rupee 10% weaker", us=-0.20, india=-0.20, rupee=-0.10),
)


@dataclass(frozen=True, slots=True)
class Contribution:
    ticker: str
    change: float


@dataclass(slots=True)
class StressResult:
    key: str
    name: str
    kind: str  # "historical" or "hypothetical"
    start: date | None
    end: date | None
    nav_before: float
    nav_after: float
    change: float
    change_pct: float
    drivers: list[Contribution] = field(default_factory=list)
    proxied: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class _Item:
    label: str
    ticker: str | None
    currency: str
    value: float  # base currency, today
    country: str | None
    option: OptionsPosition | None = None
    spot: float = 0.0
    vol: float = 0.0
    years: float = 0.0
    size: float = 0.0


class _History:
    """Daily closes and USD rates, read once per request."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.closes: dict[str, tuple[list[date], list[float]]] = {}
        self.fx: dict[str, tuple[list[date], list[float]]] = {}

    def _bars(self, ticker: str) -> tuple[list[date], list[float]]:
        if ticker not in self.closes:
            rows = self.session.exec(
                select(col(PriceBar.ts), col(PriceBar.close))
                .where(
                    col(PriceBar.instrument_id) == instrument_of(ticker),
                    PriceBar.interval == "1d",
                )
                .order_by(col(PriceBar.ts))
            ).all()
            self.closes[ticker] = ([ts.date() for ts, _ in rows], [float(c) for _, c in rows])
        return self.closes[ticker]

    def close_on(self, ticker: str, day: date, *, strict_start: bool = False) -> float | None:
        days, closes = self._bars(ticker)
        i = bisect.bisect_right(days, day) - 1
        if i < 0:
            return None
        # A window's start needs a bar within a week of it, not years before.
        if strict_start and (day - days[i]).days > 7:
            return None
        return closes[i]

    def daily_returns(self, ticker: str) -> dict[date, float]:
        days, closes = self._bars(ticker)
        days, closes = days[-(BETA_SESSIONS + 1) :], closes[-(BETA_SESSIONS + 1) :]
        return {
            days[i]: closes[i] / closes[i - 1] - 1 for i in range(1, len(days)) if closes[i - 1]
        }

    def usd_rate(self, ccy: str, day: date) -> float | None:
        if ccy == "USD":
            return 1.0
        if ccy not in self.fx:
            rows = self.session.exec(
                select(col(FxRate.date), col(FxRate.usd_rate))
                .where(FxRate.currency == ccy)
                .order_by(col(FxRate.date))
            ).all()
            self.fx[ccy] = ([d for d, _ in rows], [float(r) for _, r in rows])
        days, rates = self.fx[ccy]
        i = bisect.bisect_right(days, day) - 1
        return rates[i] if i >= 0 else None


def beta(stock: dict[date, float], index: dict[date, float]) -> float | None:
    common = sorted(set(stock) & set(index))
    if len(common) < 60:
        return None
    xs = [index[d] for d in common]
    ys = [stock[d] for d in common]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    var = sum((x - mx) ** 2 for x in xs)
    if var == 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / var


def _bs(item: _Item, spot: float) -> float:
    assert item.option is not None
    return black_scholes(
        spot=spot,
        strike=float(item.option.strike),
        time_to_expiry_years=item.years,
        volatility=item.vol,
        risk_free_rate=RISK_FREE_RATE,
        option_type=item.option.option_type.value,
    ).value


def _items(
    session: Session, portfolio: Portfolio, valuation: PortfolioValuation, history: _History
) -> list[_Item]:
    base = portfolio.base_currency or "USD"
    options = session.exec(
        select(OptionsPosition).where(
            OptionsPosition.portfolio_id == portfolio.id,
            OptionsPosition.status == OptionStatus.OPEN,
        )
    ).all()
    tickers = sorted({p.ticker for p in valuation.positions} | {o.ticker for o in options})
    info = classifications(session, tickers)

    def to_base(amount: float, ccy: str) -> float:
        if ccy == base:
            return amount
        try:
            return float(
                fx_convert(session, Decimal(str(amount)), from_currency=ccy, to_currency=base)
            )
        except LookupError:
            return amount

    items: list[_Item] = []
    for p in valuation.positions:
        country = info[p.ticker].country if p.ticker in info else None
        items.append(
            _Item(
                p.ticker,
                p.ticker,
                p.currency,
                to_base(float(p.market_value_native), p.currency),
                country,
            )
        )
    for c in valuation.cash_by_currency:
        if c.currency != base and c.amount != 0:
            items.append(
                _Item(
                    f"{c.currency} cash",
                    None,
                    c.currency,
                    to_base(float(c.amount), c.currency),
                    None,
                )
            )
    today = utcnow().date()
    for o in options:
        _days, closes = history._bars(o.ticker)
        if not closes:
            continue
        vol = historical_volatility([Decimal(str(c)) for c in closes[-61:]])
        country = info[o.ticker].country if o.ticker in info else None
        size = float(o.shares_per_contract) * o.quantity
        item = _Item(
            f"{o.ticker} option", o.ticker, "USD", 0.0, country, o, closes[-1], vol,
            max((o.expiry - today).days / 365.0, 0.0), size,
        )  # fmt: skip
        items.append(item)
    return items


def _apply(
    items: list[_Item],
    moves: dict[str, float],
    fx_moves: dict[str, float],
    *,
    base: str,
    usd_to_base: float,
) -> tuple[float, list[Contribution]]:
    """Total change in base money, and each holding's part."""
    parts: list[Contribution] = []
    for item in items:
        fx = fx_moves.get(item.currency, 0.0) if item.currency != base else 0.0
        if item.option is not None:
            local = moves.get(item.label, 0.0)
            before = _bs(item, item.spot)
            after = _bs(item, item.spot * (1 + local))
            value_now = before * item.size * usd_to_base
            change = after * item.size * usd_to_base * (1 + fx) - value_now
        else:
            local = moves.get(item.label, 0.0)
            change = item.value * ((1 + local) * (1 + fx) - 1)
        parts.append(Contribution(item.label, change))
    return sum(p.change for p in parts), parts


def run_stress(
    session: Session, portfolio: Portfolio, valuation: PortfolioValuation, *, nav_base: float
) -> list[StressResult]:
    base = portfolio.base_currency or "USD"
    history = _History(session)
    items = _items(session, portfolio, valuation, history)
    today = utcnow().date()
    base_usd_now = history.usd_rate(base, today) or 1.0
    usd_to_base = 1.0 / base_usd_now
    currencies = {i.currency for i in items if i.currency != base}
    out: list[StressResult] = []

    for window in HISTORICAL:
        moves: dict[str, float] = {}
        proxied: list[str] = []
        missing: list[str] = []
        for item in items:
            if item.ticker is None:
                continue
            start = history.close_on(item.ticker, window.start, strict_start=True)
            end = history.close_on(item.ticker, window.end)
            if start and end:
                moves[item.label] = end / start - 1
                continue
            index = proxy_for(item.ticker)
            i_start = history.close_on(index, window.start, strict_start=True)
            i_end = history.close_on(index, window.end)
            b = beta(history.daily_returns(item.ticker), history.daily_returns(index))
            if i_start and i_end and b is not None:
                moves[item.label] = (i_end / i_start - 1) * b
                proxied.append(item.label)
            else:
                missing.append(item.label)
        fx_moves = {}
        for ccy in currencies:
            # Base per unit of ccy at each end, from the USD rates.
            ends = [history.usd_rate(ccy, d) for d in (window.start, window.end)]
            bases = [history.usd_rate(base, d) for d in (window.start, window.end)]
            if None in ends or None in bases:
                missing.append(f"{ccy} rate")
                continue
            fx_moves[ccy] = (ends[1] / bases[1]) / (ends[0] / bases[0]) - 1  # type: ignore[operator]
        total, parts = _apply(items, moves, fx_moves, base=base, usd_to_base=usd_to_base)
        out.append(_result(window.key, window.name, "historical", window.start, window.end,
                           nav_base, total, parts, proxied, missing))  # fmt: skip

    for shock in HYPOTHETICAL:
        moves = {}
        for item in items:
            if item.country == "US":
                moves[item.label] = shock.us
            elif item.country == "IN":
                moves[item.label] = shock.india
        fx_moves = {}
        if shock.rupee:
            # USD per INR falls by `rupee`; in base terms:
            if base == "USD":
                fx_moves["INR"] = shock.rupee
            elif base == "INR":
                fx_moves["USD"] = 1 / (1 + shock.rupee) - 1
        total, parts = _apply(items, moves, fx_moves, base=base, usd_to_base=usd_to_base)
        out.append(_result(shock.key, shock.name, "hypothetical", None, None,
                           nav_base, total, parts, [], []))  # fmt: skip
    return out


def _result(
    key: str,
    name: str,
    kind: str,
    start: date | None,
    end: date | None,
    nav: float,
    total: float,
    parts: list[Contribution],
    proxied: list[str],
    missing: list[str],
) -> StressResult:
    drivers = sorted((p for p in parts if p.change), key=lambda p: p.change)[:5]
    return StressResult(
        key=key,
        name=name,
        kind=kind,
        start=start,
        end=end,
        nav_before=nav,
        nav_after=nav + total,
        change=total,
        change_pct=(total / nav * 100) if nav else 0.0,
        drivers=drivers,
        proxied=proxied,
        missing=missing,
    )
