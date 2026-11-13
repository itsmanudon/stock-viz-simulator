"""Phase 5.5: walk-forward and capped sweeps, stored and rerunnable."""

from __future__ import annotations

import random
import time as clock
from datetime import date, datetime, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient
from jose import jwt as jose_jwt
from sqlmodel import Session

from stockviz.models import PriceBar, User
from stockviz.schemas import BacktestIn
from stockviz.services.backtest.walkforward import MAX_SETTINGS, walk_forward, windows
from stockviz.settings import get_settings
from tests.symbols import seed_symbols

SECRET = get_settings().internal_api_token
START = date(2018, 1, 1)


def _headers(user_id: int) -> dict[str, str]:
    token = jose_jwt.encode({"sub": str(user_id)}, SECRET, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


def _seed(session: Session, years: int = 6, seed: int = 3) -> None:
    seed_symbols(session, "AAPL")
    rng = random.Random(seed)
    price = Decimal(100)
    day = START
    for _ in range(int(years * 365.25)):
        if day.weekday() < 5:
            price = max(Decimal(5), price * Decimal(str(1 + rng.gauss(0.0003, 0.015))))
            close = price.quantize(Decimal("0.01"))
            session.add(
                PriceBar(
                    ticker="AAPL",
                    ts=datetime.combine(day, datetime.min.time()),
                    interval="1d",
                    open=close,
                    high=close,
                    low=close,
                    close=close,
                    volume=1,
                    source="test",
                )
            )
        day += timedelta(days=1)
    session.commit()


def _body(**extra) -> dict:
    return {
        "ticker": "AAPL",
        "from": "2018-01-01",
        "to": "2023-12-31",
        "initial_cash": "10000",
        "strategy": {"type": "sma_crossover", "short_window": 10, "long_window": 50},
        **extra,
    }


def test_windows_follow_the_owner_defaults() -> None:
    plan = windows(date(2018, 1, 1), date(2023, 12, 31), 3, 1, 1)
    assert plan[0] == (date(2018, 1, 1), date(2020, 12, 31), date(2021, 1, 1), date(2021, 12, 31))
    assert [w[2].year for w in plan] == [2021, 2022, 2023]


def test_walk_forward_scores_only_out_of_sample(session: Session) -> None:
    _seed(session)
    result = walk_forward(session, BacktestIn.model_validate(_body())).result

    assert result["tried"] == 15 and len(result["windows"]) == 3  # SMA grid: 15 (short < long)
    assert result["equity_curve"][0]["date"] >= "2021-01-01"  # no in-sample day
    grid = {(s["short_window"], s["long_window"]) for s in [w["chosen"] for w in result["windows"]]}
    assert all(short in (5, 10, 20, 50) and long_ in (50, 100, 150, 200) for short, long_ in grid)
    # Capital carries over: each window starts where the last ended.
    assert Decimal(result["summary"]["final_nav"]) == Decimal(result["equity_curve"][-1]["nav"])


def test_endpoints_store_and_rerun_identically(session: Session, client: TestClient) -> None:
    _seed(session)
    user = User(email="wf@stockviz.dev", name="W")
    session.add(user)
    session.commit()
    assert user.id is not None
    headers = _headers(user.id)

    wf = client.post("/v1/experiments/walk-forward", json={"backtest": _body()}, headers=headers)
    assert wf.status_code == 201, wf.text
    run = wf.json()
    assert run["kind"] == "walk_forward" and run["result"]["result_kind"] == "walk_forward"
    rerun = client.post(f"/v1/experiments/runs/{run['id']}/rerun", headers=headers).json()
    assert rerun["status"] == "identical"

    grid = [{"type": "sma_crossover", "short_window": s, "long_window": 60} for s in (5, 10, 20)]
    sw = client.post(
        "/v1/experiments/sweep",
        json={"backtest": _body(), "grid": grid, "score": "total_return"},
        headers=headers,
    ).json()
    returns = [r["summary"]["total_return"] for r in sw["result"]["runs"]]
    assert sw["result"]["tried"] == 3 and returns == sorted(returns, reverse=True)
    assert (
        client.post(f"/v1/experiments/runs/{sw['id']}/rerun", headers=headers).json()["status"]
        == "identical"
    )

    too_many = [grid[0]] * (MAX_SETTINGS + 1)
    refused = client.post(
        "/v1/experiments/sweep", json={"backtest": _body(), "grid": too_many}, headers=headers
    )
    assert refused.status_code == 422
    short = client.post(
        "/v1/experiments/walk-forward",
        json={"backtest": _body(**{"from": "2023-01-01"})},
        headers=headers,
    )
    assert short.status_code == 400


def test_fifty_settings_over_ten_years_fit_in_a_request(session: Session) -> None:
    _seed(session, years=10)
    grid = [
        {"type": "sma_crossover", "short_window": s, "long_window": long_}
        for s in (3, 5, 8, 10, 15, 20, 25, 30, 40, 50)
        for long_ in (60, 90, 120, 160, 200)
    ]
    body = BacktestIn.model_validate(_body(**{"to": "2027-12-31"}))
    began = clock.perf_counter()
    result = walk_forward(session, body, grid=grid).result
    elapsed = clock.perf_counter() - began
    assert result["tried"] == 50 and len(result["windows"]) == 7
    assert elapsed < 30, elapsed  # measured locally; see the delivery log
