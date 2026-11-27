"""A LightGBM factor ranker with SHAP attributions, walk-forward (A9.8, M8.4).

Laptop only (owner, 27 Nov 2026: Chronos, LightGBM and SHAP run in ``lab/``,
never in the API image). Reads the export's daily ``price_bars``.

- **Features** at each month-end, from bars up to that day only: returns over
  21, 63, 126 and 252 sessions, 12-1 momentum (252 less the last 21), 20- and
  60-session volatility of daily returns, distance from the 252-session high,
  and 20 over 60-session average volume.
- **Target:** the cross-sectional percentile rank of the next ``HORIZON``
  sessions' return.
- **Walk-forward:** for each test month, train on months whose target window
  ended before the test month began (a ``HORIZON`` gap, so no label overlaps
  the test), at least ``MIN_TRAIN_MONTHS`` of them.
- **Score:** each test month's Spearman rank IC between prediction and the
  realised forward return; mean, t-statistic and hit rate across months,
  beside the same for 12-1 momentum alone (the baseline the model must beat).
- **SHAP:** mean |SHAP| per feature from ``TreeExplainer`` on the last
  model's training rows, so the ranking says which inputs it leaned on.

Survivorship: the export's symbols as listed today. In-sample choices (the
feature list, the parameters) are fixed here, not tuned on the test months.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

HORIZON = 21
MIN_TRAIN_MONTHS = 24
MIN_SYMBOLS = 8
FEATURES = (
    "ret_21",
    "ret_63",
    "ret_126",
    "ret_252",
    "mom_12_1",
    "vol_20",
    "vol_60",
    "dist_high_252",
    "volume_trend",
)
PARAMS = {
    "objective": "regression",
    "learning_rate": 0.05,
    "num_leaves": 15,
    "min_data_in_leaf": 20,
    "feature_fraction": 0.9,
    "bagging_fraction": 0.8,
    "bagging_freq": 1,
    "seed": 7,
    "deterministic": True,
    "verbose": -1,
}
ROUNDS = 150


def load_panel(root: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Wide closes and volumes (date x ticker) from the export's daily bars."""
    glob = str(root / "price_bars" / "**" / "*.parquet")
    frame = duckdb.sql(
        f"SELECT ticker, CAST(ts AS DATE) AS day, CAST(close AS DOUBLE) AS close, "
        f"CAST(volume AS DOUBLE) AS volume FROM read_parquet('{glob}', hive_partitioning=true)"
    ).df()
    closes = frame.pivot_table(index="day", columns="ticker", values="close").sort_index()
    volumes = frame.pivot_table(index="day", columns="ticker", values="volume").sort_index()
    closes.index = pd.to_datetime(closes.index)
    volumes.index = pd.to_datetime(volumes.index)
    return closes, volumes


def features_at(closes: pd.DataFrame, volumes: pd.DataFrame) -> pd.DataFrame:
    """Long frame (date, ticker, features..., fwd) at each month's last session."""
    rets = closes.pct_change()
    feats = {
        "ret_21": closes / closes.shift(21) - 1,
        "ret_63": closes / closes.shift(63) - 1,
        "ret_126": closes / closes.shift(126) - 1,
        "ret_252": closes / closes.shift(252) - 1,
        "mom_12_1": closes.shift(21) / closes.shift(252) - 1,
        "vol_20": rets.rolling(20).std(),
        "vol_60": rets.rolling(60).std(),
        "dist_high_252": closes / closes.rolling(252).max() - 1,
        "volume_trend": volumes.rolling(20).mean() / volumes.rolling(60).mean(),
    }
    fwd = closes.shift(-HORIZON) / closes - 1
    month_ends = closes.groupby(closes.index.to_period("M")).tail(1).index
    rows = []
    for name, wide in feats.items():
        s = wide.loc[month_ends].stack()
        s.name = name
        rows.append(s)
    f = pd.concat(rows, axis=1)
    f["fwd"] = fwd.loc[month_ends].stack()
    f.index.names = ["date", "ticker"]
    return f.reset_index()


def _spearman(a: np.ndarray, b: np.ndarray) -> float | None:
    if len(a) < 3:
        return None
    ra = pd.Series(a).rank().to_numpy()
    rb = pd.Series(b).rank().to_numpy()
    if np.std(ra) == 0 or np.std(rb) == 0:
        return None
    return float(np.corrcoef(ra, rb)[0, 1])


def _summary(ics: list[float]) -> dict[str, float | int | None]:
    n = len(ics)
    if n == 0:
        return {"months": 0, "mean_ic": None, "t_stat": None, "hit_rate": None}
    mean = float(np.mean(ics))
    sd = float(np.std(ics, ddof=1)) if n > 1 else 0.0
    return {
        "months": n,
        "mean_ic": mean,
        "t_stat": mean / (sd / math.sqrt(n)) if sd > 0 else None,
        "hit_rate": float(np.mean([v > 0 for v in ics])),
    }


@dataclass
class RankerReport:
    first_test: str | None
    last_test: str | None
    symbols: int
    model: dict[str, float | int | None]
    baseline: dict[str, float | int | None]
    monthly: list[dict[str, object]] = field(default_factory=list)
    shap: list[tuple[str, float]] = field(default_factory=list)
    latest: list[tuple[str, float]] = field(default_factory=list)
    latest_date: str | None = None
    notes: list[str] = field(default_factory=list)


def walk_forward(panel: pd.DataFrame) -> RankerReport:
    import lightgbm as lgb
    import shap

    data = panel.dropna(subset=list(FEATURES)).copy()
    labelled = data.dropna(subset=["fwd"]).copy()
    labelled["target"] = labelled.groupby("date")["fwd"].rank(pct=True)
    dates = sorted(labelled["date"].unique())
    model_ics: list[float] = []
    base_ics: list[float] = []
    monthly: list[dict[str, object]] = []
    booster = None
    train = labelled.iloc[0:0]
    for i, test_date in enumerate(dates):
        # A training month's label ends HORIZON sessions after it: keep months
        # at least two month-ends back so no label overlaps the test month.
        train = labelled[labelled["date"].isin(dates[: max(0, i - 1)])]
        if train["date"].nunique() < MIN_TRAIN_MONTHS:
            continue
        test = labelled[labelled["date"] == test_date]
        if len(test) < MIN_SYMBOLS:
            continue
        booster = lgb.train(
            PARAMS,
            lgb.Dataset(train[list(FEATURES)], label=train["target"]),
            num_boost_round=ROUNDS,
        )
        pred = booster.predict(test[list(FEATURES)])
        ic = _spearman(np.asarray(pred), test["fwd"].to_numpy())
        base = _spearman(test["mom_12_1"].to_numpy(), test["fwd"].to_numpy())
        if ic is None or base is None:
            continue
        model_ics.append(ic)
        base_ics.append(base)
        monthly.append(
            {
                "date": str(pd.Timestamp(test_date).date()),
                "ic": ic,
                "baseline_ic": base,
                "n": len(test),
            }
        )
    report = RankerReport(
        first_test=monthly[0]["date"] if monthly else None,  # type: ignore[arg-type]
        last_test=monthly[-1]["date"] if monthly else None,  # type: ignore[arg-type]
        symbols=int(data["ticker"].nunique()),
        model=_summary(model_ics),
        baseline=_summary(base_ics),
        monthly=monthly,
        notes=[
            f"Walk-forward, {HORIZON}-session horizon, a one-month gap before each test month; "
            f"at least {MIN_TRAIN_MONTHS} training months.",
            "Survivorship-biased: today's symbol list. Parameters fixed in code, not tuned on tests.",
            "Rank IC is association, not a promise of returns; not advice.",
        ],
    )
    if booster is not None and len(train):
        explainer = shap.TreeExplainer(booster)
        values = np.asarray(explainer.shap_values(train[list(FEATURES)]))
        importance = np.abs(values).mean(axis=0)
        report.shap = sorted(
            ((f, float(v)) for f, v in zip(FEATURES, importance, strict=True)),
            key=lambda x: -x[1],
        )
        latest_date = data["date"].max()
        latest = data[data["date"] == latest_date]
        scores = booster.predict(latest[list(FEATURES)])
        report.latest = sorted(
            ((t, float(s)) for t, s in zip(latest["ticker"], scores, strict=True)),
            key=lambda x: -x[1],
        )
        report.latest_date = str(pd.Timestamp(latest_date).date())
    return report
