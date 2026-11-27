"""Volatility summary from the stored US chains (A9.4, M6.3).

From the nightly ``option_quotes`` snapshots of one symbol, priced at the
stored close of each snapshot date:

- **Term structure:** per expiry of the newest snapshot, the at-the-money IV
  (the mean IV of the strike closest to spot) and the days to expiry.
- **25-delta skew:** per expiry, the IV of the put nearest -0.25 delta minus
  the call nearest +0.25 delta (Black-Scholes deltas at each contract's IV).
  Positive: puts are dearer, the usual equity skew.
- **VRP:** the ATM IV of the expiry nearest 30 days minus the realised
  volatility of the last 21 sessions (close to close, annualised): what the
  options charged over what the stock did. A positive number is not a signal
  on its own; realised volatility can rise.
- **IV rank and percentile:** that 30-day ATM IV against every stored
  snapshot's within the last 365 days: rank = (now - low) / (high - low),
  percentile = the share of snapshots at or below now. Fewer than 20
  snapshots: not reported.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, timedelta
from itertools import pairwise

from sqlmodel import Session, col, select

from stockviz.models import PriceBar
from stockviz.models.option_quote import OptionChainQuote
from stockviz.services.instruments import instrument_ids
from stockviz.services.options.pricing import black_scholes, risk_free_rate

TARGET_DAYS = 30
REALISED_SESSIONS = 21
MIN_SNAPSHOTS = 20


@dataclass(frozen=True)
class Quote:
    expiry: date
    strike: float
    option_type: str
    iv: float


@dataclass
class VolSummary:
    ticker: str
    snapshot_date: date | None = None
    spot: float | None = None
    term: list[dict[str, object]] = field(default_factory=list)
    atm_30d: float | None = None
    realised_21d: float | None = None
    vrp: float | None = None
    iv_rank: float | None = None
    iv_percentile: float | None = None
    snapshots: int = 0
    reason: str | None = None


def atm_iv(quotes: list[Quote], expiry: date, spot: float) -> float | None:
    rows = [q for q in quotes if q.expiry == expiry]
    if not rows:
        return None
    closest = min(rows, key=lambda q: abs(q.strike - spot)).strike
    ivs = [q.iv for q in rows if q.strike == closest]
    return sum(ivs) / len(ivs)


def skew_25d(quotes: list[Quote], expiry: date, spot: float, on: date, rate: float) -> float | None:
    years = max((expiry - on).days, 0) / 365.0
    if years <= 0:
        return None
    best: dict[str, tuple[float, float]] = {}
    for q in quotes:
        if q.expiry != expiry:
            continue
        d = black_scholes(spot=spot, strike=q.strike, time_to_expiry_years=years,
                          volatility=q.iv, risk_free_rate=rate, option_type=q.option_type).delta  # fmt: skip
        target = 0.25 if q.option_type == "call" else -0.25
        gap = abs(d - target)
        if q.option_type not in best or gap < best[q.option_type][0]:
            best[q.option_type] = (gap, q.iv)
    if "call" not in best or "put" not in best:
        return None
    return best["put"][1] - best["call"][1]


def nearest_expiry(expiries: list[date], on: date) -> date | None:
    return min(expiries, key=lambda e: abs((e - on).days - TARGET_DAYS)) if expiries else None


def realised_vol(closes: list[float]) -> float | None:
    if len(closes) < REALISED_SESSIONS + 1:
        return None
    window = closes[-(REALISED_SESSIONS + 1) :]
    rets = [math.log(b / a) for a, b in pairwise(window) if a > 0 and b > 0]
    if len(rets) < 2:
        return None
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    return math.sqrt(var * 252)


def summarise(
    ticker: str,
    snapshots: dict[date, list[Quote]],
    closes: dict[date, float],
    rate: float,
) -> VolSummary:
    """The summary from snapshots and closes (pure)."""
    out = VolSummary(ticker=ticker)
    usable = sorted(d for d in snapshots if _close_on(closes, d) is not None and snapshots[d])
    if not usable:
        out.reason = "No stored option chain with a close to price it (US stocks, nightly)."
        return out
    on = usable[-1]
    spot = _close_on(closes, on)
    assert spot is not None
    out.snapshot_date, out.spot = on, spot
    quotes = snapshots[on]
    for expiry in sorted({q.expiry for q in quotes}):
        if expiry < on:
            continue
        iv = atm_iv(quotes, expiry, spot)
        skew = skew_25d(quotes, expiry, spot, on, rate)
        out.term.append({
            "expiry": expiry, "days": (expiry - on).days,
            "atm_iv": None if iv is None else round(iv, 6),
            "skew_25d": None if skew is None else round(skew, 6),
        })  # fmt: skip
    target = nearest_expiry([e for e in {q.expiry for q in quotes} if e > on], on)
    out.atm_30d = None if target is None else _round(atm_iv(quotes, target, spot))
    history = [closes[d] for d in sorted(closes) if d <= on]
    out.realised_21d = _round(realised_vol(history))
    if out.atm_30d is not None and out.realised_21d is not None:
        out.vrp = round(out.atm_30d - out.realised_21d, 6)
    series: list[float] = []
    for d in usable:
        if d < on - timedelta(days=365):
            continue
        s = _close_on(closes, d)
        e = nearest_expiry([x for x in {q.expiry for q in snapshots[d]} if x > d], d)
        if s is None or e is None:
            continue
        iv = atm_iv(snapshots[d], e, s)
        if iv is not None:
            series.append(iv)
    out.snapshots = len(series)
    if len(series) >= MIN_SNAPSHOTS and out.atm_30d is not None:
        lo, hi = min(series), max(series)
        out.iv_rank = round((out.atm_30d - lo) / (hi - lo), 4) if hi > lo else None
        out.iv_percentile = round(sum(1 for v in series if v <= out.atm_30d) / len(series), 4)
    return out


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 6)


def _close_on(closes: dict[date, float], day: date) -> float | None:
    """The close on ``day`` or the latest before it (a snapshot taken before the bar)."""
    if day in closes:
        return closes[day]
    earlier = [d for d in closes if d <= day]
    return closes[max(earlier)] if earlier else None


def vol_summary(session: Session, ticker: str) -> VolSummary:
    ticker = ticker.upper()
    iid = instrument_ids(session, [ticker]).get(ticker)
    if iid is None:
        return VolSummary(ticker=ticker, reason="Unknown symbol.")
    rows = session.exec(
        select(OptionChainQuote).where(
            col(OptionChainQuote.instrument_id) == iid,
            col(OptionChainQuote.implied_volatility).is_not(None),
        )
    ).all()
    snapshots: dict[date, list[Quote]] = {}
    for r in rows:
        if r.implied_volatility and r.implied_volatility > 0:
            snapshots.setdefault(r.snapshot_date, []).append(
                Quote(r.expiry, float(r.strike), r.option_type, float(r.implied_volatility))
            )
    bars = session.exec(
        select(PriceBar).where(col(PriceBar.ticker) == ticker, col(PriceBar.interval) == "1d")
    ).all()
    closes = {b.ts.date(): float(b.close) for b in bars}
    return summarise(ticker, snapshots, closes, risk_free_rate("USD"))
