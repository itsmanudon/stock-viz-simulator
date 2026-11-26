"""A7.7 (M7.5): multi-factor models on the rotation engine."""

from __future__ import annotations

import math
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlmodel import Session

from stockviz.services.backtest.rotation_run import factor_scores
from tests.test_rotation import _days, _seed_all, _sym, body


def _z(values: list[float]) -> list[float]:
    mean = sum(values) / len(values)
    sd = math.sqrt(sum((v - mean) ** 2 for v in values) / (len(values) - 1))
    return [(v - mean) / sd for v in values]


def test_weighted_z_scores_by_hand() -> None:
    days = _days(2)
    syms = [_sym(t, days, [100, 101], [None, None]) for t in ("A", "B", "C")]
    momentum = {"A": [0.10, 0.20], "B": [0.00, 0.10], "C": [-0.10, 0.30]}
    volatility = {"A": [0.02, 0.02], "B": [0.01, 0.03], "C": [0.03, 0.01]}
    values: dict[str, list[list[float | None]]] = {
        t: [list(momentum[t]), list(volatility[t])] for t in "ABC"
    }
    factors = [SimpleNamespace(weight=2.0, higher_is_better=True),
               SimpleNamespace(weight=1.0, higher_is_better=False)]  # fmt: skip
    out = {s.ticker: s.score for s in factor_scores(syms, values, factors)}
    zm = _z([0.10, 0.00, -0.10])
    zv = _z([0.02, 0.01, 0.03])
    for i, t in enumerate("ABC"):
        assert out[t][0] == 2.0 * zm[i] - zv[i]


def test_too_few_symbols_or_no_spread_leaves_the_date_unscored() -> None:
    days = _days(1)
    two = [_sym(t, days, [100], [None]) for t in ("A", "B")]
    f = [SimpleNamespace(weight=1.0, higher_is_better=True)]
    assert all(s.score == [None] for s in factor_scores(two, {"A": [[1.0]], "B": [[2.0]]}, f))
    three = [_sym(t, days, [100], [None]) for t in ("A", "B", "C")]
    flat: dict[str, list[list[float | None]]] = {t: [[1.0]] for t in "ABC"}
    assert all(s.score == [None] for s in factor_scores(three, flat, f))
    missing = {"A": [[1.0]], "B": [[None]], "C": [[3.0]], "D": [[2.0]]}
    four = [*three, _sym("D", days, [100], [None])]
    scored = {s.ticker: s.score[0] for s in factor_scores(four, missing, f)}
    assert scored["B"] is None and scored["A"] is not None  # B lacks a factor that day


def _factor_body(**over) -> dict:
    out = body(**over)
    out.pop("ranking")
    out["factors"] = [
        {"name": "momentum", "expression": "pct_change(close, 60)", "weight": 2},
        {"name": "low volatility", "expression": "atr(14) / close", "weight": 1,
         "higher_is_better": False},
    ]  # fmt: skip
    return out


def test_factor_model_runs_reruns_identically_and_reports_its_factors(
    client: TestClient, session: Session
) -> None:
    _seed_all(session)
    res = client.post("/v1/backtest/rotation", json=_factor_body())
    assert res.status_code == 200, res.text
    out = res.json()
    roles = [r["role"] for r in out["rules"]]
    assert roles == ["ranking", "factor", "factor"]
    assert (
        out["rules"][0]["canonical"].startswith("2 x z(") and "-z(" in out["rules"][0]["canonical"]
    )
    assert out["rebalances"] and out["checks"]["trials"]["n"] >= 1
    again = client.post("/v1/backtest/rotation", json=_factor_body()).json()
    assert again["strategy_hash"] == out["strategy_hash"]
    assert again["rebalances"] == out["rebalances"]
    # A different weight is a different strategy, and counts in the same trial family.
    other = _factor_body()
    other["factors"][0]["weight"] = 1
    changed = client.post("/v1/backtest/rotation", json=other).json()
    assert changed["strategy_hash"] != out["strategy_hash"]
    # Same skeleton (numbers as #), so the trial ledger counts it in the same family.
    assert changed["checks"]["trials"]["n"] > out["checks"]["trials"]["n"]


def test_exactly_one_of_ranking_or_factors(client: TestClient) -> None:
    both = _factor_body()
    both["ranking"] = "close"
    assert client.post("/v1/backtest/rotation", json=both).status_code == 422
    neither = _factor_body()
    neither.pop("factors")
    assert client.post("/v1/backtest/rotation", json=neither).status_code == 422
