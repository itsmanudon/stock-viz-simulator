"""A9.2 (M8.2, M8.3): forecasts with skill against a random walk and realised coverage."""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from decimal import Decimal

import numpy as np
from fastapi.testclient import TestClient
from sqlmodel import Session

from stockviz.models import PriceBar
from stockviz.services import forecasts as fc
from tests.symbols import seed_symbols


def _clustered(n: int, seed: int = 3) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Persistent log-volatility (AR(1), phi 0.97) with a noisy high-low range."""
    rng = np.random.default_rng(seed)
    logv = np.zeros(n)
    for t in range(1, n):
        logv[t] = 0.97 * logv[t - 1] + 0.2 * rng.normal()
    sigma = 0.01 * np.exp(logv)
    close = 100 * np.exp(np.cumsum(sigma * rng.normal(size=n)))
    spread = sigma * np.abs(rng.normal(size=n)) * 2 + 1e-4
    return close * np.exp(spread / 2), close * np.exp(-spread / 2), close


def test_har_beats_the_random_walk_on_clustered_volatility() -> None:
    high, low, _close = _clustered(1600)
    out = fc.har_forecast(high, low)
    assert out.reason is None and out.test_days >= 200
    # A noisy one-day proxy: the random walk copies the noise, HAR averages it out.
    assert out.skill_mse is not None and out.skill_mse > 0
    assert out.skill_qlike is not None and out.skill_qlike > 0
    assert out.next_day_vol is not None and out.next_day_vol > 0


def test_har_is_out_of_sample() -> None:
    high, low, _ = _clustered(1000)
    base = fc.har_forecast(high, low)
    changed_high = high.copy()
    changed_high[-1] *= 1.5  # the last bar only enters the final forecast
    after = fc.har_forecast(changed_high, low)
    assert after.test_days == base.test_days
    assert after.next_day_vol != base.next_day_vol


def test_conformal_quantile_rank() -> None:
    scores = np.arange(1.0, 11.0)  # 1..10
    assert fc.conformal_q(scores, 0.8) == 9.0  # ceil(11 x 0.8) = 9th smallest
    assert fc.conformal_q(scores, 0.95) is None  # ceil(11 x 0.95) = 11 > n


def test_cones_cover_about_their_level_on_iid_returns() -> None:
    rng = np.random.default_rng(11)
    n = 900
    close = 100 * np.exp(np.cumsum(0.01 * rng.normal(size=n)))
    dates = [date(2022, 1, 3) + timedelta(days=i) for i in range(n)]
    out = fc.price_cones(dates, close)
    assert out.reason is None and len(out.cones) == 6
    for cone in out.cones:
        assert cone.realised_coverage is not None
        # Overlapping h-day outcomes: 250 test days hold about 250 / h independent
        # windows, so the tolerance widens with the horizon.
        tolerance = 0.08 if cone.horizon == 1 else 0.12 if cone.horizon == 5 else 0.2
        assert abs(cone.realised_coverage - cone.level) < tolerance, cone
        assert cone.lower is not None and cone.upper is not None
        assert cone.lower < close[-1] < cone.upper
    one = next(c for c in out.cones if c.horizon == 1 and c.level == 0.8)
    twenty = next(c for c in out.cones if c.horizon == 20 and c.level == 0.8)
    assert (twenty.upper or 0) - (twenty.lower or 0) > (one.upper or 0) - (one.lower or 0)


def test_short_history_gives_reasons() -> None:
    assert fc.har_forecast(np.ones(50) * 1.01, np.ones(50)).reason
    assert fc.price_cones([date(2026, 1, 1)], np.array([100.0])).reason


def test_route(session: Session, client: TestClient) -> None:
    seed_symbols(session, "ACME", currency="USD")
    high, low, close = _clustered(700, seed=5)
    start = datetime(2023, 1, 2)
    for i in range(700):
        session.add(PriceBar(ticker="ACME", ts=start + timedelta(days=i), interval="1d",
                             open=Decimal(f"{close[i]:.4f}"), high=Decimal(f"{high[i]:.4f}"),
                             low=Decimal(f"{low[i]:.4f}"), close=Decimal(f"{close[i]:.4f}"),
                             volume=1, source="test"))  # fmt: skip
    session.commit()
    body = client.get("/v1/symbols/ACME/forecast").json()
    assert body["volatility"]["skill_qlike"] is not None
    assert {(c["horizon"], c["level"]) for c in body["cones"]} == {
        (h, lv) for h in (1, 5, 20) for lv in (0.8, 0.95)
    }
    assert "random walk" in body["method"]["scoring"]
    assert math.isfinite(body["last_close"])
