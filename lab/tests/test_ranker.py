"""A9.8 (M8.4): the walk-forward ranker on a planted cross-section (synthetic)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from stockviz_lab import ranker


def _panel(
    n_tickers: int = 20, n_days: int = 1500, seed: int = 3
) -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    days = pd.bdate_range("2018-01-01", periods=n_days)
    vols = np.linspace(0.008, 0.03, n_tickers)
    # Planted: higher-volatility names drift up faster, so their next month is better.
    drifts = (vols - vols.mean()) * 0.2
    noise = rng.normal(size=(n_days, n_tickers)) * vols
    closes = pd.DataFrame(100 * np.exp(np.cumsum(drifts + noise, axis=0)), index=days,
                          columns=[f"T{i:02d}" for i in range(n_tickers)])  # fmt: skip
    volumes = pd.DataFrame(
        1e5 * (1 + rng.random((n_days, n_tickers))), index=days, columns=closes.columns
    )
    return closes, volumes


def test_features_never_read_later_bars() -> None:
    closes, volumes = _panel()
    cut = closes.index[900]
    base = ranker.features_at(closes, volumes)
    changed = closes.copy()
    changed.loc[changed.index > cut] *= 3.0
    after = ranker.features_at(changed, volumes)
    cols = list(ranker.FEATURES)
    a = base[base["date"] <= cut].set_index(["date", "ticker"])[cols]
    b = after[after["date"] <= cut].set_index(["date", "ticker"])[cols]
    pd.testing.assert_frame_equal(a, b)


def test_walk_forward_finds_the_planted_effect_out_of_sample() -> None:
    closes, volumes = _panel()
    report = ranker.walk_forward(ranker.features_at(closes, volumes))
    assert report.model["months"] and report.model["months"] > 20
    assert report.model["mean_ic"] is not None and report.model["mean_ic"] > 0.05
    assert report.model["t_stat"] is not None and report.model["t_stat"] > 2
    assert {f for f, _v in report.shap} == set(ranker.FEATURES)
    assert all(v >= 0 for _f, v in report.shap)
    top = [f for f, _v in report.shap[:3]]
    assert any(f.startswith("vol_") for f in top)
    assert len(report.latest) == 20 and report.latest_date


def test_noise_gives_no_edge() -> None:
    rng = np.random.default_rng(11)
    days = pd.bdate_range("2018-01-01", periods=1500)
    closes = pd.DataFrame(100 * np.exp(np.cumsum(rng.normal(size=(1500, 20)) * 0.015, axis=0)), index=days,
                          columns=[f"N{i:02d}" for i in range(20)])  # fmt: skip
    volumes = pd.DataFrame(1e5, index=days, columns=closes.columns)
    report = ranker.walk_forward(ranker.features_at(closes, volumes))
    assert report.model["mean_ic"] is not None and abs(report.model["mean_ic"]) < 0.08
