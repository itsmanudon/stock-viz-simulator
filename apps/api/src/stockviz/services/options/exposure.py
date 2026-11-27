"""Gamma and delta exposure from the stored US chain (A7.9, M6.2).

On the newest ``option_quotes`` snapshot of a symbol (yfinance, the nightly
``options-snapshot``), with its implied volatility and open interest per
contract, priced with A4's Black-Scholes at the stored close:

- **GEX per strike** = gamma x open interest x 100 x spot^2 x 0.01: the dollar
  change in delta hedges for a 1% move. **Convention (an assumption, said on
  screen):** dealers are long the calls and short the puts customers trade,
  so calls count positive and puts negative (SqueezeMetrics' convention).
- **DEX per strike** = delta x open interest x 100 x spot: open interest's
  delta in dollars (calls positive, puts negative), not anyone's position.
- **Gamma flip:** total GEX re-priced across a spot grid (+-20%, every
  contract's gamma at that spot); the spot where it changes sign nearest
  today's. **Call and put walls:** the strikes with the most call and put
  open interest. **Expected move (1 day):** spot x at-the-money IV x
  sqrt(1/252), ATM = the nearest expiry's strike closest to spot.

Volatility-regime context, not direction. Contracts without IV or open
interest are skipped and counted.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date

from sqlmodel import Session, col, func, select

from stockviz.models import PriceBar
from stockviz.models.option_quote import OptionChainQuote as OptionQuote
from stockviz.services.instruments import instrument_ids
from stockviz.services.options.pricing import black_scholes, risk_free_rate

CONTRACT = 100
GRID_STEPS = 41
GRID_SPAN = 0.20
NOTE = (
    "Volatility-regime context, not direction. GEX assumes dealers are long calls and "
    "short puts; open interest is from the newest nightly snapshot (end of day)."
)


@dataclass(frozen=True)
class Contract:
    expiry: date
    strike: float
    option_type: str
    iv: float
    oi: int


@dataclass
class Exposure:
    ticker: str
    snapshot_date: date | None
    spot: float | None
    expiries: list[date] = field(default_factory=list)
    strikes: list[dict[str, float]] = field(default_factory=list)
    total_gex: float | None = None
    total_dex: float | None = None
    gamma_flip: float | None = None
    call_wall: float | None = None
    put_wall: float | None = None
    expected_move_1d: float | None = None
    atm_iv: float | None = None
    used: int = 0
    skipped: int = 0
    reason: str | None = None


def _years(expiry: date, on: date) -> float:
    return max((expiry - on).days, 0) / 365.0


def contract_greeks(c: Contract, spot: float, on: date, rate: float) -> tuple[float, float]:
    """(gamma, delta) of one contract at ``spot``."""
    p = black_scholes(spot=spot, strike=c.strike, time_to_expiry_years=_years(c.expiry, on),
                      volatility=c.iv, risk_free_rate=rate, option_type=c.option_type)  # fmt: skip
    return p.gamma, p.delta


def gex_of(c: Contract, gamma: float, spot: float) -> float:
    sign = 1.0 if c.option_type == "call" else -1.0
    return sign * gamma * c.oi * CONTRACT * spot * spot * 0.01


def total_gex_at(contracts: list[Contract], spot: float, on: date, rate: float) -> float:
    return sum(gex_of(c, contract_greeks(c, spot, on, rate)[0], spot) for c in contracts)


def gamma_flip(contracts: list[Contract], spot: float, on: date, rate: float) -> float | None:
    """The spot where total GEX changes sign nearest ``spot`` (linear between grid points)."""
    grid = [
        spot * (1 - GRID_SPAN + 2 * GRID_SPAN * i / (GRID_STEPS - 1)) for i in range(GRID_STEPS)
    ]
    values = [total_gex_at(contracts, s, on, rate) for s in grid]
    flips: list[float] = []
    for (s0, v0), (s1, v1) in zip(
        zip(grid, values, strict=True), zip(grid[1:], values[1:], strict=True), strict=False
    ):
        if v0 == 0:
            flips.append(s0)
        elif v0 * v1 < 0:
            flips.append(s0 + (s1 - s0) * (-v0) / (v1 - v0))
    return min(flips, key=lambda s: abs(s - spot)) if flips else None


def exposure_from(
    ticker: str, contracts: list[Contract], spot: float, on: date, rate: float, skipped: int
) -> Exposure:
    """The figures for one snapshot (pure)."""
    out = Exposure(ticker=ticker, snapshot_date=on, spot=spot, skipped=skipped, used=len(contracts))
    if not contracts:
        out.reason = "No contract in the snapshot has both an implied volatility and open interest."
        return out
    out.expiries = sorted({c.expiry for c in contracts})
    per: dict[float, dict[str, float]] = {}
    for c in contracts:
        gamma, delta = contract_greeks(c, spot, on, rate)
        row = per.setdefault(c.strike, {"strike": c.strike, "gex": 0.0, "dex": 0.0,
                                         "call_oi": 0.0, "put_oi": 0.0})  # fmt: skip
        row["gex"] += gex_of(c, gamma, spot)
        row["dex"] += delta * c.oi * CONTRACT * spot
        row["call_oi" if c.option_type == "call" else "put_oi"] += c.oi
    out.strikes = [{k: round(v, 4) for k, v in per[s].items()} for s in sorted(per)]
    out.total_gex = round(sum(r["gex"] for r in per.values()), 2)
    out.total_dex = round(sum(r["dex"] for r in per.values()), 2)
    calls = [r for r in per.values() if r["call_oi"] > 0]
    puts = [r for r in per.values() if r["put_oi"] > 0]
    out.call_wall = (
        max(calls, key=lambda r: (r["call_oi"], -r["strike"]))["strike"] if calls else None
    )
    out.put_wall = max(puts, key=lambda r: (r["put_oi"], r["strike"]))["strike"] if puts else None
    flip = gamma_flip(contracts, spot, on, rate)
    out.gamma_flip = None if flip is None else round(flip, 4)
    nearest = out.expiries[0]
    atm = [c for c in contracts if c.expiry == nearest]
    closest = min(atm, key=lambda c: abs(c.strike - spot)).strike
    ivs = [c.iv for c in atm if c.strike == closest]
    out.atm_iv = round(sum(ivs) / len(ivs), 6)
    out.expected_move_1d = round(spot * out.atm_iv * math.sqrt(1 / 252), 4)
    return out


def exposure(session: Session, ticker: str) -> Exposure:
    ticker = ticker.upper()
    iid = instrument_ids(session, [ticker]).get(ticker)
    empty = Exposure(ticker=ticker, snapshot_date=None, spot=None)
    if iid is None:
        empty.reason = "Unknown symbol."
        return empty
    on = session.exec(
        select(func.max(OptionQuote.snapshot_date)).where(col(OptionQuote.instrument_id) == iid)
    ).one()
    if on is None:
        empty.reason = "No option chain stored for this symbol (US stocks, nightly)."
        return empty
    bar = session.exec(
        select(PriceBar)
        .where(col(PriceBar.ticker) == ticker, col(PriceBar.interval) == "1d")
        .order_by(col(PriceBar.ts).desc())
    ).first()
    if bar is None:
        empty.reason = "No stored close to price the chain at."
        return empty
    rows = session.exec(
        select(OptionQuote).where(
            col(OptionQuote.instrument_id) == iid, col(OptionQuote.snapshot_date) == on
        )
    ).all()
    contracts: list[Contract] = []
    skipped = 0
    for r in rows:
        if not r.implied_volatility or not r.open_interest or r.expiry < on:
            skipped += 1
            continue
        contracts.append(Contract(r.expiry, float(r.strike), r.option_type,
                                  float(r.implied_volatility), int(r.open_interest)))  # fmt: skip
    return exposure_from(ticker, contracts, float(bar.close), on, risk_free_rate("USD"), skipped)
