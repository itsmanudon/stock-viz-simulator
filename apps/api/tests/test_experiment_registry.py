"""Phase 5.4: stored backtests rerun identically, or say the data changed."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient
from jose import jwt as jose_jwt
from sqlmodel import Session, select

from stockviz.models import ExperimentRun, PriceBar, User
from stockviz.settings import get_settings
from tests.symbols import seed_symbols

SECRET = get_settings().internal_api_token

BACKTEST = {
    "ticker": "AAPL",
    "from": "2024-01-01",
    "to": "2024-01-31",
    "initial_cash": "1000",
    "strategy": {"type": "sma_crossover", "short_window": 2, "long_window": 3},
    "spread_bps": 10,
    "fee_schedule": "us_equity_2026",
}


def _headers(user_id: int) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {jose_jwt.encode({'sub': str(user_id)}, SECRET, algorithm='HS256')}"
    }


def _user(session: Session, email: str) -> int:
    user = User(email=email, name="R")
    session.add(user)
    session.commit()
    assert user.id is not None
    return user.id


def _seed(session: Session) -> None:
    seed_symbols(session, "AAPL")
    for i, close in enumerate((10, 10, 10, 30, 30, 60, 40, 20, 20, 25)):
        price = Decimal(close)
        session.add(
            PriceBar(
                ticker="AAPL",
                ts=datetime(2024, 1, 1) + timedelta(days=i),
                interval="1d",
                open=price,
                high=price,
                low=price,
                close=price,
                volume=1,
                source="test",
            )
        )
    session.commit()


def test_a_saved_run_reruns_identically(session: Session, client: TestClient) -> None:
    _seed(session)
    headers = _headers(_user(session, "runs@stockviz.dev"))
    experiment = client.post(
        "/v1/experiments",
        json={"name": "SMA 2/3", "hypothesis": "Short crosses pay"},
        headers=headers,
    ).json()

    saved = client.post(
        "/v1/experiments/runs",
        json={"backtest": BACKTEST, "experiment_id": experiment["id"]},
        headers=headers,
    )
    assert saved.status_code == 201, saved.text
    run = saved.json()
    assert run["execution_profile"] == "next_open/v1"
    assert run["fee_schedule"] == "us_equity_2026"
    assert run["bar_count"] == 10 and len(run["dataset_fingerprint"]) == 64
    assert run["result"]["trades"]  # the stored result is the full backtest

    # Same request through the public endpoint: the same answer.
    public = client.post("/v1/backtest", json=BACKTEST).json()
    assert public == run["result"]

    report = client.post(f"/v1/experiments/runs/{run['id']}/rerun", headers=headers).json()
    assert report == {
        "status": "identical",
        "stored_fingerprint": run["dataset_fingerprint"],
        "current_fingerprint": run["dataset_fingerprint"],
        "differences": [],
    }
    listed = client.get("/v1/experiments", headers=headers).json()
    assert listed[0]["run_count"] == 1


def test_changed_data_is_reported_not_compared(session: Session, client: TestClient) -> None:
    _seed(session)
    headers = _headers(_user(session, "changed@stockviz.dev"))
    run = client.post("/v1/experiments/runs", json={"backtest": BACKTEST}, headers=headers).json()

    bar = session.exec(select(PriceBar).where(PriceBar.ts == datetime(2024, 1, 6))).one()
    bar.close = Decimal(61)
    session.add(bar)
    session.commit()

    report = client.post(f"/v1/experiments/runs/{run['id']}/rerun", headers=headers).json()
    assert report["status"] == "data_changed"
    assert report["current_fingerprint"] != report["stored_fingerprint"]


def test_a_code_change_shows_as_different(session: Session, client: TestClient) -> None:
    _seed(session)
    headers = _headers(_user(session, "code@stockviz.dev"))
    run = client.post("/v1/experiments/runs", json={"backtest": BACKTEST}, headers=headers).json()
    # Stand-in for a code change: the stored result no longer matches.
    row = session.get(ExperimentRun, run["id"])
    assert row is not None
    row.result = {**row.result, "warmup_bars": 99}
    session.add(row)
    session.commit()

    report = client.post(f"/v1/experiments/runs/{run['id']}/rerun", headers=headers).json()
    assert report["status"] == "different" and report["differences"] == ["warmup_bars"]


def test_runs_are_private(session: Session, client: TestClient) -> None:
    _seed(session)
    owner = _headers(_user(session, "owner@stockviz.dev"))
    other = _headers(_user(session, "other@stockviz.dev"))
    run = client.post("/v1/experiments/runs", json={"backtest": BACKTEST}, headers=owner).json()

    assert client.get(f"/v1/experiments/runs/{run['id']}", headers=other).status_code == 404
    assert client.post(f"/v1/experiments/runs/{run['id']}/rerun", headers=other).status_code == 404
    assert client.get("/v1/experiments/runs", headers=other).json() == []
    assert client.get("/v1/experiments/runs").status_code == 401
    listed = client.get("/v1/experiments/runs", headers=owner).json()
    assert len(listed) == 1 and listed[0]["result"] is None  # the list carries summaries only
    assert client.delete(f"/v1/experiments/runs/{run['id']}", headers=owner).status_code == 204
