"""Today's holdings replayed over past sessions, in the base currency (Phase 8.3).

The scenario calendar is the last :data:`WINDOW_SESSIONS` dates on which any
held stock or option underlying has a stored daily bar. On each date:

- a stock's local return is its close-to-close return to that bar. Before
  its first stored bar it takes its market's index (``^NSEI`` for Indian
  listings, ``^GSPC`` otherwise) and the day counts as proxied; on a date
  its own market was shut it is 0, and the next bar carries the move;
- a currency's return is the move in base units per unit, from the stored
  USD rates (carried forward over days without a rate);
- the base-currency return is ``(1 + local)(1 + currency) - 1``.

Stocks and foreign cash scale linearly. Options are repriced in full with
Black-Scholes at the scenario's spot, today's volatility and the horizon
taken off their time to expiry, so a long option's loss stops at its value.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from itertools import pairwise

import numpy as np
from sqlmodel import Session, col, select

from stockviz.models import OptionsPosition, OptionStatus, Portfolio, PriceBar
from stockviz.models.market import FxRate
from stockviz.services.instruments import instrument_of
from stockviz.services.markets.calendar import venue_for_ticker
from stockviz.services.options.pricing import black_scholes, historical_volatility
from stockviz.services.options.trade import RISK_FREE_RATE
from stockviz.services.risk.engine import compound_windows
from stockviz.services.trading.fx import convert as fx_convert
from stockviz.services.trading.portfolio import PortfolioValuation

WINDOW_SESSIONS = 500
MIN_SESSIONS = 250
LOOKBACK_BARS = 520
SESSIONS_PER_YEAR = 252


def proxy_for(ticker: str) -> str:
    return "^NSEI" if venue_for_ticker(ticker) == "XBOM" else "^GSPC"


@dataclass(frozen=True, slots=True)
class Excluded:
    ticker: str
    reason: str


@dataclass(frozen=True, slots=True)
class Proxied:
    ticker: str
    proxy: str
    days: int


@dataclass(slots=True)
class Scenarios:
    base_currency: str
    nav_base: float
    dates: list[date] = field(default_factory=list)
    pnl: dict[int, np.ndarray] = field(default_factory=dict)
    """Horizon (sessions) -> portfolio P&L per scenario, base currency."""
    included: int = 0
    excluded: list[Excluded] = field(default_factory=list)
    proxied: list[Proxied] = field(default_factory=list)
    reason: str | None = None


def _closes(session: Session, ticker: str) -> list[tuple[date, float]]:
    rows = session.exec(
        select(col(PriceBar.ts), col(PriceBar.close))
        .where(col(PriceBar.instrument_id) == instrument_of(ticker), PriceBar.interval == "1d")
        .order_by(col(PriceBar.ts).desc())
        .limit(LOOKBACK_BARS + 1)
    ).all()
    return [(ts.date(), float(close)) for ts, close in reversed(rows)]


def _returns(closes: list[tuple[date, float]]) -> dict[date, float]:
    return {day: (close / prev - 1) for (_, prev), (day, close) in pairwise(closes) if prev > 0}


class _FxSeries:
    """Base units per unit of each currency on any date, carried forward."""

    def __init__(self, session: Session, currencies: set[str], base: str, since: date) -> None:
        wanted = {c for c in currencies | {base} if c != "USD"}
        self.base = base
        self.series: dict[str, tuple[list[date], list[float]]] = {}
        if wanted:
            rows = session.exec(
                select(col(FxRate.currency), col(FxRate.date), col(FxRate.usd_rate))
                .where(col(FxRate.currency).in_(wanted), FxRate.date >= since)
                .order_by(col(FxRate.date))
            ).all()
            for ccy, day, rate in rows:
                days, rates = self.series.setdefault(ccy, ([], []))
                days.append(day)
                rates.append(float(rate))

    def _usd(self, ccy: str, day: date) -> float | None:
        if ccy == "USD":
            return 1.0
        days, rates = self.series.get(ccy, ([], []))
        i = bisect.bisect_right(days, day) - 1
        return rates[i] if i >= 0 else None

    def rate(self, ccy: str, day: date) -> float | None:
        """Base per unit of ``ccy`` on ``day``: USD per ccy over USD per base."""
        num, den = self._usd(ccy, day), self._usd(self.base, day)
        if num is None or den is None or den == 0:
            return None
        return num / den

    def returns(self, ccy: str, dates: list[date], before: date) -> np.ndarray | None:
        if ccy == self.base:
            return np.zeros(len(dates))
        prev = self.rate(ccy, before)
        out = []
        for day in dates:
            now = self.rate(ccy, day)
            if now is None or prev is None:
                return None
            out.append(now / prev - 1)
            prev = now
        return np.array(out)


def build_scenarios(
    session: Session,
    portfolio: Portfolio,
    valuation: PortfolioValuation,
    *,
    horizons: tuple[int, ...],
    as_of: date,
) -> Scenarios:
    assert portfolio.id is not None
    base = portfolio.base_currency or "USD"
    nav_display = valuation.total_value
    try:
        nav_base = fx_convert(
            session, nav_display, from_currency=valuation.display_currency, to_currency=base
        )
    except LookupError:
        nav_base = nav_display
    out = Scenarios(base_currency=base, nav_base=float(nav_base))

    options = list(
        session.exec(
            select(OptionsPosition).where(
                OptionsPosition.portfolio_id == portfolio.id,
                OptionsPosition.status == OptionStatus.OPEN,
            )
        ).all()
    )
    tickers = sorted({p.ticker for p in valuation.positions} | {o.ticker for o in options})
    closes = {t: _closes(session, t) for t in tickers}
    for ticker in [t for t in tickers if len(closes[t]) < 2]:
        out.excluded.append(Excluded(ticker, "fewer than two stored closes"))
    priced = [t for t in tickers if len(closes[t]) >= 2]
    returns = {t: _returns(closes[t]) for t in priced}
    proxies = {proxy_for(t) for t in priced}
    proxy_returns = {p: _returns(_closes(session, p)) for p in proxies}

    calendar = sorted(set().union(*(returns[t].keys() for t in priced))) if priced else []
    foreign_cash = [c for c in valuation.cash_by_currency if c.currency != base and c.amount != 0]
    fx_needed = {p.currency for p in valuation.positions} | {c.currency for c in foreign_cash}
    if options:
        fx_needed.add("USD")
    since = (calendar[0] if calendar else as_of).replace(day=1)
    fx = _FxSeries(session, fx_needed, base, since)
    if not calendar and foreign_cash:
        calendar = sorted({d for days, _ in fx.series.values() for d in days})
    dates = calendar[-(WINDOW_SESSIONS + 1) :]
    before, dates = (dates[0], dates[1:]) if len(dates) > 1 else (as_of, [])
    out.dates = dates
    if len(dates) < MIN_SESSIONS:
        out.reason = f"{len(dates)} sessions of history; {MIN_SESSIONS} are needed"
        return out

    columns: list[np.ndarray] = []
    values: list[float] = []

    def local_series(ticker: str) -> np.ndarray:
        own, first = returns[ticker], closes[ticker][1][0]
        proxy, used = proxy_returns.get(proxy_for(ticker), {}), 0
        series = []
        for day in dates:
            if day in own:
                series.append(own[day])
            elif day < first:
                series.append(proxy.get(day, 0.0))
                used += 1
            else:
                series.append(0.0)
        if used:
            out.proxied.append(Proxied(ticker, proxy_for(ticker), used))
        return np.array(series)

    for position in valuation.positions:
        if position.ticker not in returns:
            continue
        ccy_ret = fx.returns(position.currency, dates, before)
        value = fx.rate(position.currency, as_of)
        if ccy_ret is None or value is None:
            out.excluded.append(Excluded(position.ticker, "no FX history for its currency"))
            continue
        local = local_series(position.ticker)
        columns.append((1 + local) * (1 + ccy_ret) - 1)
        values.append(float(position.market_value_native) * value)
        out.included += 1
    for cash in foreign_cash:
        ccy_ret = fx.returns(cash.currency, dates, before)
        value = fx.rate(cash.currency, as_of)
        if ccy_ret is None or value is None:
            out.excluded.append(Excluded(f"{cash.currency} cash", "no FX history"))
            continue
        columns.append(ccy_ret)
        values.append(float(cash.amount) * value)
        out.included += 1

    matrix = np.column_stack(columns) if columns else np.zeros((len(dates), 0))
    weights = np.array(values)
    usd_ret = fx.returns("USD", dates, before) if options else None
    usd_now = fx.rate("USD", as_of) if options else None
    option_inputs = []
    for option in options:
        if option.ticker not in returns or usd_ret is None or usd_now is None:
            out.excluded.append(Excluded(f"{option.ticker} option", "no price or FX history"))
            continue
        spot = closes[option.ticker][-1][1]
        vol = historical_volatility([Decimal(str(c)) for _, c in closes[option.ticker][-61:]])
        years = max((option.expiry - as_of).days / 365.0, 0.0)
        size = float(option.shares_per_contract) * option.quantity
        option_inputs.append((option, spot, vol, years, size, local_series(option.ticker)))
        out.included += 1

    for horizon in horizons:
        pnl = compound_windows(matrix, horizon) @ weights if len(weights) else None
        rows = len(dates) - horizon + 1
        total = pnl if pnl is not None else np.zeros(rows)
        for option, spot, vol, years, size, under in option_inputs:
            now_value = _bs(option, spot, vol, years)
            moved = compound_windows(under.reshape(-1, 1), horizon)[:, 0]
            usd_moves = compound_windows(usd_ret.reshape(-1, 1), horizon)[:, 0]  # type: ignore[union-attr]
            later = max(years - horizon / SESSIONS_PER_YEAR, 0.0)
            scenario = np.array(
                [_bs(option, spot * (1 + m), vol, later) - now_value for m in moved]
            )
            total = total + scenario * size * usd_now * (1 + usd_moves)  # type: ignore[operator]
        out.pnl[horizon] = total
    return out


def _bs(option: OptionsPosition, spot: float, vol: float, years: float) -> float:
    return black_scholes(
        spot=spot,
        strike=float(option.strike),
        time_to_expiry_years=years,
        volatility=vol,
        risk_free_rate=RISK_FREE_RATE,
        option_type=option.option_type.value,
    ).value
