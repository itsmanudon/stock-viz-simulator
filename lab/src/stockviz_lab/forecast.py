"""Chronos-2 forecast fans, scored against a random walk (A9.9, M8.1).

Laptop only (owner, 27 Nov 2026: Chronos runs in ``lab/``, never in the API
image; its weights, ``amazon/chronos-2``, Apache-2.0, about 480 MB, download
once into the Hugging Face cache on first use).

- **Fan:** the 10th, 50th and 90th percentile of the next ``horizon``
  closes, from the last ``context`` closes, as Chronos-2 gives them.
- **Score (rolling origins):** at each origin (every ``step`` sessions over
  the last ``origins`` of them) the model sees closes up to the origin only.
  At ``horizon`` sessions on:
  - **coverage:** the share of origins whose realised close fell inside the
    80% band (nominal 80%);
  - **skill:** 1 - MAE(model median) / MAE(random walk), where the random
    walk forecasts the last close. Above 0 beats it.
  - the random walk's own 80% band (from the window's past ``horizon``-session
    log returns) for the same coverage check.
- ``Predictor`` is ``(context closes) -> (q10, q50, q90) at each step``, so
  tests use a fake and never download a model.

A fan describes a distribution; it is not a forecast to trade on and not advice.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np

Quantiles = tuple[np.ndarray, np.ndarray, np.ndarray]
Predictor = Callable[[np.ndarray, int], Quantiles]
MODEL_ID = "amazon/chronos-2"


def chronos_predictor(model_id: str = MODEL_ID) -> Predictor:
    import torch
    from chronos import BaseChronosPipeline

    pipeline = BaseChronosPipeline.from_pretrained(model_id, device_map="cpu")

    def predict(context: np.ndarray, horizon: int) -> Quantiles:
        series = torch.tensor(context, dtype=torch.float32).reshape(1, 1, -1)
        quantiles, _mean = pipeline.predict_quantiles(
            series, prediction_length=horizon, quantile_levels=[0.1, 0.5, 0.9]
        )
        q = quantiles[0][0].numpy()  # (horizon, 3)
        return q[:, 0], q[:, 1], q[:, 2]

    return predict


def random_walk_band(context: np.ndarray, horizon: int) -> tuple[float, float]:
    """10th and 90th percentile of past ``horizon``-session log returns, applied to the last close."""
    logs = np.log(context)
    if len(logs) <= horizon + 20:
        return float("nan"), float("nan")
    moves = logs[horizon:] - logs[:-horizon]
    lo, hi = np.quantile(moves, [0.1, 0.9])
    last = context[-1]
    return float(last * math.exp(lo)), float(last * math.exp(hi))


@dataclass
class Score:
    origins: int
    coverage: float | None
    rw_coverage: float | None
    mae: float | None
    rw_mae: float | None
    skill: float | None


@dataclass
class TickerForecast:
    ticker: str
    last_date: str
    last_close: float
    horizon: int
    q10: list[float]
    q50: list[float]
    q90: list[float]
    score: Score
    notes: list[str] = field(default_factory=list)


def evaluate(
    closes: np.ndarray,
    predict: Predictor,
    *,
    horizon: int,
    context: int,
    origins: int,
    step: int,
) -> Score:
    hits = rw_hits = 0
    errs: list[float] = []
    rw_errs: list[float] = []
    count = 0
    last_origin = len(closes) - horizon - 1
    starts = list(range(last_origin, context - 1, -step))[:origins]
    for o in sorted(starts):
        ctx = closes[o - context + 1 : o + 1]
        actual = closes[o + horizon]
        q10, q50, q90 = predict(ctx, horizon)
        lo, mid, hi = float(q10[-1]), float(q50[-1]), float(q90[-1])
        rw_lo, rw_hi = random_walk_band(closes[: o + 1], horizon)
        if math.isnan(rw_lo):
            continue
        count += 1
        hits += lo <= actual <= hi
        rw_hits += rw_lo <= actual <= rw_hi
        errs.append(abs(mid - actual) / actual)
        rw_errs.append(abs(ctx[-1] - actual) / actual)
    if count == 0:
        return Score(0, None, None, None, None, None)
    mae, rw_mae = float(np.mean(errs)), float(np.mean(rw_errs))
    return Score(
        origins=count,
        coverage=hits / count,
        rw_coverage=rw_hits / count,
        mae=mae,
        rw_mae=rw_mae,
        skill=1 - mae / rw_mae if rw_mae > 0 else None,
    )


def forecast_ticker(
    ticker: str,
    dates: list[str],
    closes: np.ndarray,
    predict: Predictor,
    *,
    horizon: int = 21,
    context: int = 512,
    origins: int = 36,
    step: int = 21,
) -> TickerForecast:
    if len(closes) < context + horizon + 2:
        raise ValueError(f"{ticker}: needs {context + horizon + 2} closes, has {len(closes)}")
    q10, q50, q90 = predict(closes[-context:], horizon)
    score = evaluate(closes, predict, horizon=horizon, context=context, origins=origins, step=step)
    return TickerForecast(
        ticker=ticker,
        last_date=dates[-1],
        last_close=float(closes[-1]),
        horizon=horizon,
        q10=[float(v) for v in q10],
        q50=[float(v) for v in q50],
        q90=[float(v) for v in q90],
        score=score,
        notes=[
            f"Fan from the last {context} closes; scored at {score.origins} rolling origins "
            f"{step} sessions apart, each seeing closes up to its origin only.",
            "Coverage near 80% is a calibrated band; skill above 0 beats a random walk.",
        ],
    )
