"""A9.9 (M8.1): the forecast scoring, with fake predictors (no model download)."""

from __future__ import annotations

import math

import numpy as np
import pytest

from stockviz_lab import forecast as fc


def _walk(n: int = 1200, vol: float = 0.01, seed: int = 5) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return 100 * np.exp(np.cumsum(rng.normal(0, vol, n)))


def _rw_predictor(vol: float) -> fc.Predictor:
    """A calibrated random-walk fan: the true model of _walk."""

    def predict(context: np.ndarray, horizon: int):
        steps = np.arange(1, horizon + 1)
        z = 1.2815515655446004
        last = context[-1]
        return (
            last * np.exp(-z * vol * np.sqrt(steps)),
            np.full(horizon, last),
            last * np.exp(z * vol * np.sqrt(steps)),
        )

    return predict


def test_a_calibrated_fan_covers_about_80_percent_and_has_no_skill() -> None:
    closes = _walk(3000)
    s = fc.evaluate(closes, _rw_predictor(0.01), horizon=21, context=256, origins=100, step=21)
    assert s.origins == 100
    assert s.coverage is not None and 0.65 <= s.coverage <= 0.92
    assert s.skill == pytest.approx(0.0, abs=1e-9)  # the median is the last close


def test_a_too_narrow_fan_under_covers() -> None:
    closes = _walk(3000)
    s = fc.evaluate(closes, _rw_predictor(0.002), horizon=21, context=256, origins=100, step=21)
    assert s.coverage is not None and s.coverage < 0.4


def test_the_predictor_never_sees_the_future() -> None:
    closes = _walk()
    seen: list[int] = []

    def spy(context: np.ndarray, horizon: int):
        # The context must end at an origin: the value right after it is unseen.
        idx = int(np.where(np.isclose(closes, context[-1]))[0][0])
        seen.append(idx)
        assert len(context) == 256 and idx + horizon < len(closes)
        return _rw_predictor(0.01)(context, horizon)

    fc.evaluate(closes, spy, horizon=21, context=256, origins=10, step=21)
    assert seen and max(seen) == len(closes) - 21 - 1


def test_forecast_ticker_returns_the_fan_and_refuses_short_history() -> None:
    closes = _walk()
    dates = [f"d{i}" for i in range(len(closes))]
    out = fc.forecast_ticker(
        "X", dates, closes, _rw_predictor(0.01), horizon=10, context=256, origins=5
    )
    assert len(out.q50) == 10 and out.q10[-1] < out.q50[-1] < out.q90[-1]
    assert out.last_date == dates[-1] and math.isclose(out.last_close, closes[-1])
    with pytest.raises(ValueError, match="needs"):
        fc.forecast_ticker("Y", dates[:100], closes[:100], _rw_predictor(0.01))
