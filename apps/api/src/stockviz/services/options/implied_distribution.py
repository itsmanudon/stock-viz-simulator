"""Option-implied vs model distribution of a price at expiry (A9.13, M8.5).

From the newest stored chain snapshot (``option_quotes``) of one US symbol:

- **Implied (risk-neutral) density** for one expiry, by Breeden-Litzenberger:
  ``f(K) = e^{rT} d²C/dK²``. The smile is the out-of-the-money IVs (puts
  below spot, calls above; the mean where both quote a strike), smoothed by a
  least-squares quadratic in standardised log-moneyness ``ln(K/S)/sqrt(T)``
  over strikes within ``FIT_SD`` of spot with an IV between 3% and 300%, and
  held flat beyond the fitted range (raw quotes are noisy; linear
  interpolation through them gave large negative densities on real chains);
  calls are priced with
  Black-Scholes on a log-spaced grid of ``GRID`` strikes over +-``SPAN_SD``
  standard deviations, and the second difference gives the density. Negative
  values (a smile that is not arbitrage-free there) are cut to zero and their
  mass reported. Needs ``MIN_STRIKES`` strikes spanning spot.
- **Model density:** lognormal at the same horizon with the A9.2 HAR-RV
  volatility forecast (annualised), else the realised volatility of the last
  21 sessions, drift ``r - σ²/2`` (the same forward as the options), so the
  two differ only in shape and width.
- **Compared:** quantiles (5, 25, 50, 75, 95%), the chance of ending more than
  ``MOVE`` below or above spot, and the implied ATM volatility against the
  model's. The implied density is risk-neutral: it carries the market's risk
  premium (fatter left tail), so it is not a forecast of the real-world one.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date

import numpy as np

from stockviz.services.options.pricing import black_scholes

GRID = 401
SPAN_SD = 4.0
MIN_STRIKES = 5
MOVE = 0.10
FIT_SD = 2.5
IV_RANGE = (0.03, 3.0)
QUANTILES = (0.05, 0.25, 0.5, 0.75, 0.95)
CURVE_POINTS = 81


@dataclass(frozen=True)
class SmilePoint:
    strike: float
    iv: float


@dataclass
class Distribution:
    expiry: date | None = None
    days: int | None = None
    spot: float | None = None
    implied_atm_vol: float | None = None
    model_vol: float | None = None
    model_vol_source: str | None = None
    implied_quantiles: list[float] = field(default_factory=list)
    model_quantiles: list[float] = field(default_factory=list)
    implied_p_down: float | None = None
    implied_p_up: float | None = None
    model_p_down: float | None = None
    model_p_up: float | None = None
    negative_mass: float | None = None
    curve: list[tuple[float, float, float]] = field(default_factory=list)
    """(price, implied density, model density), ``CURVE_POINTS`` of them."""
    strikes_used: int = 0
    reason: str | None = None


def smile(quotes: list[tuple[float, str, float]], spot: float) -> list[SmilePoint]:
    """OTM IVs by strike from ``(strike, type, iv)``; the mean where both sides quote."""
    by: dict[float, list[float]] = {}
    for strike, kind, iv in quotes:
        if iv <= 0 or not math.isfinite(iv):
            continue
        otm = (kind == "put" and strike <= spot) or (kind == "call" and strike >= spot)
        if otm:
            by.setdefault(strike, []).append(iv)
    return [SmilePoint(k, sum(v) / len(v)) for k, v in sorted(by.items())]


@dataclass(frozen=True)
class SmileFit:
    coefficients: tuple[float, float, float]
    x_min: float
    x_max: float
    points: int

    def iv(self, k: np.ndarray, spot: float, t: float) -> np.ndarray:
        x = np.clip(np.log(k / spot) / math.sqrt(t), self.x_min, self.x_max)
        a, b, c = self.coefficients
        return np.clip(a + b * x + c * x * x, IV_RANGE[0], IV_RANGE[1])


def fit_smile(points: list[SmilePoint], spot: float, t: float) -> SmileFit | None:
    """Quadratic IV in ln(K/S)/sqrt(T) over the usable strikes near spot."""
    pts = [p for p in points if IV_RANGE[0] <= p.iv <= IV_RANGE[1]]
    if not pts:
        return None
    atm = min(pts, key=lambda p: abs(p.strike - spot)).iv
    xs = np.array([math.log(p.strike / spot) / math.sqrt(t) for p in pts])
    ys = np.array([p.iv for p in pts])
    keep = np.abs(xs) <= FIT_SD * atm
    if keep.sum() < MIN_STRIKES or (xs[keep] < 0).sum() == 0 or (xs[keep] > 0).sum() == 0:
        return None
    coef = np.polyfit(xs[keep], ys[keep], 2)
    return SmileFit((float(coef[2]), float(coef[1]), float(coef[0])),
                    float(xs[keep].min()), float(xs[keep].max()), int(keep.sum()))  # fmt: skip


def _quantiles(x: np.ndarray, pdf: np.ndarray) -> list[float]:
    cdf = np.cumsum((pdf[1:] + pdf[:-1]) / 2 * np.diff(x))
    cdf = np.concatenate([[0.0], cdf])
    cdf /= cdf[-1]
    return [round(float(np.interp(q, cdf, x)), 4) for q in QUANTILES]


def _prob_below(x: np.ndarray, pdf: np.ndarray, level: float) -> float:
    mask = x <= level
    if mask.sum() < 2:
        return 0.0
    total = np.trapezoid(pdf, x)
    return float(np.trapezoid(pdf[mask], x[mask]) / total)


def lognormal_pdf(x: np.ndarray, spot: float, vol: float, t: float, r: float) -> np.ndarray:
    s = vol * math.sqrt(t)
    mu = math.log(spot) + (r - vol * vol / 2) * t
    with np.errstate(divide="ignore", invalid="ignore"):
        out = np.exp(-((np.log(x) - mu) ** 2) / (2 * s * s)) / (x * s * math.sqrt(2 * math.pi))
    return np.nan_to_num(out)


def distribution(
    points: list[SmilePoint],
    *,
    spot: float,
    t: float,
    r: float,
    model_vol: float | None,
    model_vol_source: str | None,
) -> Distribution:
    out = Distribution(spot=spot, model_vol=model_vol, model_vol_source=model_vol_source)
    out.strikes_used = len(points)
    below = [p for p in points if p.strike < spot]
    above = [p for p in points if p.strike > spot]
    if len(points) < MIN_STRIKES or not below or not above:
        out.reason = f"Needs at least {MIN_STRIKES} out-of-the-money strikes on both sides of spot."
        return out
    if t <= 0:
        out.reason = "The expiry has passed."
        return out
    fit = fit_smile(points, spot, t)
    if fit is None:
        out.reason = f"Needs at least {MIN_STRIKES} usable strikes near spot on both sides."
        return out
    out.strikes_used = fit.points
    atm = float(fit.iv(np.array([spot]), spot, t)[0])
    out.implied_atm_vol = round(atm, 4)
    sd = atm * math.sqrt(t)
    k = spot * np.exp(np.linspace(-SPAN_SD * sd, SPAN_SD * sd, GRID))
    ivs = fit.iv(k, spot, t)
    calls = np.array([
        black_scholes(spot=spot, strike=float(kk), time_to_expiry_years=t, volatility=float(v),
                      risk_free_rate=r, option_type="call").value
        for kk, v in zip(k, ivs, strict=True)
    ], dtype=float)  # fmt: skip
    # Second derivative on the non-uniform grid (three-point formula).
    h1, h2 = k[1:-1] - k[:-2], k[2:] - k[1:-1]
    d2 = 2 * (calls[2:] * h1 - calls[1:-1] * (h1 + h2) + calls[:-2] * h2) / (h1 * h2 * (h1 + h2))
    pdf = math.exp(r * t) * d2
    x = k[1:-1]
    neg = np.clip(pdf, None, 0)
    total = float(np.trapezoid(np.abs(pdf), x))
    out.negative_mass = round(float(-np.trapezoid(neg, x)) / total, 4) if total else None
    pdf = np.clip(pdf, 0, None)
    if float(np.trapezoid(pdf, x)) <= 0:
        out.reason = "The smile gives no positive density."
        return out
    pdf = pdf / np.trapezoid(pdf, x)
    out.implied_quantiles = _quantiles(x, pdf)
    out.implied_p_down = round(_prob_below(x, pdf, spot * (1 - MOVE)), 4)
    out.implied_p_up = round(1 - _prob_below(x, pdf, spot * (1 + MOVE)), 4)
    model = None
    if model_vol and model_vol > 0:
        model = lognormal_pdf(x, spot, model_vol, t, r)
        model = model / np.trapezoid(model, x)
        out.model_quantiles = _quantiles(x, model)
        out.model_p_down = round(_prob_below(x, model, spot * (1 - MOVE)), 4)
        out.model_p_up = round(1 - _prob_below(x, model, spot * (1 + MOVE)), 4)
    idx = np.linspace(0, len(x) - 1, CURVE_POINTS).round().astype(int)
    out.curve = [
        (
            round(float(x[i]), 4),
            round(float(pdf[i]), 8),
            round(float(model[i]), 8) if model is not None else 0.0,
        )
        for i in idx
    ]
    return out


def load(session, ticker: str, expiry: date | None = None) -> Distribution:
    """The distribution for ``ticker``'s newest stored snapshot (read only)."""
    from sqlmodel import col, select

    from stockviz.models.option_quote import OptionChainQuote
    from stockviz.services import forecasts as fc
    from stockviz.services.instruments import instrument_ids
    from stockviz.services.options.pricing import risk_free_rate
    from stockviz.services.options.vol_summary import nearest_expiry, realised_vol
    from stockviz.services.seasonality import bars_hlc

    iid = instrument_ids(session, [ticker]).get(ticker)
    if iid is None:
        return Distribution(reason="Unknown symbol.")
    newest = session.exec(
        select(col(OptionChainQuote.snapshot_date))
        .where(col(OptionChainQuote.instrument_id) == iid)
        .order_by(col(OptionChainQuote.snapshot_date).desc())
        .limit(1)
    ).first()
    if newest is None:
        return Distribution(reason="No option chain is stored for this symbol.")
    rows = session.exec(
        select(OptionChainQuote).where(
            col(OptionChainQuote.instrument_id) == iid,
            col(OptionChainQuote.snapshot_date) == newest,
        )
    ).all()
    expiries = sorted({r.expiry for r in rows if r.expiry > newest})
    chosen = expiry if expiry in expiries else nearest_expiry(expiries, newest)
    if chosen is None:
        return Distribution(reason="The stored snapshot has no future expiry.")
    dates, high, low, close = bars_hlc(session, ticker)
    spot = next(
        (c for d, c in zip(reversed(dates), reversed(close), strict=True) if d <= newest), None
    )
    if spot is None:
        return Distribution(expiry=chosen, reason="No stored close on or before the snapshot.")
    quotes = [
        (float(r.strike), r.option_type, float(r.implied_volatility))
        for r in rows
        if r.expiry == chosen and r.implied_volatility
    ]
    hist_close = [c for d, c in zip(dates, close, strict=True) if d <= newest]
    hist_hi = [h for d, h in zip(dates, high, strict=True) if d <= newest]
    hist_lo = [lo for d, lo in zip(dates, low, strict=True) if d <= newest]
    vol, source = None, None
    if hist_close:
        har = fc.har_forecast(np.array(hist_hi), np.array(hist_lo))
        if har.next_day_vol:
            vol, source = har.next_day_vol, "HAR-RV forecast (A9.2)"
        else:
            rv = realised_vol([float(c) for c in hist_close])
            if rv:
                vol, source = rv, "realised volatility, last 21 sessions"
    out = distribution(
        smile(quotes, float(spot)),
        spot=float(spot),
        t=(chosen - newest).days / 365,
        r=risk_free_rate("USD"),
        model_vol=vol,
        model_vol_source=source,
    )
    out.expiry, out.days = chosen, (chosen - newest).days
    return out
