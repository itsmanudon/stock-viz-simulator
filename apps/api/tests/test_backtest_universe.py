"""A1.4a (M1.5): every backtest result says it is survivorship-biased."""

from __future__ import annotations

from sqlmodel import Session

from stockviz.models import ExperimentRun
from stockviz.services.backtest.registry import result_differences
from stockviz.services.backtest.universe import universe_for
from tests.test_experiment_registry import BACKTEST, _headers, _seed, _user

PINNED = {
    "name": "pinned",
    "point_in_time": False,
    "survivorship_biased": True,
    "note": universe_for("AAPL").note,
}


def test_the_public_backtest_carries_the_stamp(session: Session, client) -> None:
    _seed(session)
    body = client.post("/v1/backtest", json=BACKTEST).json()
    assert body["universe"] == PINNED
    assert "delisted" in body["universe"]["note"]


def test_saved_runs_carry_it_and_list_it(session: Session, client) -> None:
    _seed(session)
    headers = _headers(_user(session, "u@stockviz.dev"))
    run = client.post("/v1/experiments/runs", json={"backtest": BACKTEST}, headers=headers).json()
    assert run["result"]["universe"] == PINNED and run["universe"] == PINNED
    listed = client.get("/v1/experiments/runs", headers=headers).json()
    assert listed[0]["universe"] == PINNED and listed[0]["result"] is None


def test_an_old_run_without_the_stamp_still_reruns_identically(session: Session, client) -> None:
    _seed(session)
    headers = _headers(_user(session, "old@stockviz.dev"))
    run = client.post("/v1/experiments/runs", json={"backtest": BACKTEST}, headers=headers).json()
    # A run stored before A1.4a: its result has no universe field.
    row = session.get(ExperimentRun, run["id"])
    assert row is not None
    row.result = {k: v for k, v in row.result.items() if k != "universe"}
    session.add(row)
    session.commit()

    report = client.post(f"/v1/experiments/runs/{run['id']}/rerun", headers=headers).json()
    assert report["status"] == "identical", report
    assert report["differences"] == []
    # Reading it back gives the stamp that held for it.
    again = client.get(f"/v1/experiments/runs/{run['id']}", headers=headers).json()
    assert again["universe"] == PINNED and "universe" not in again["result"]


def test_a_changed_stamp_is_still_a_difference() -> None:
    fresh = {"summary": 1, "universe": PINNED}
    assert result_differences({"summary": 1}, fresh) == []
    stored = {"summary": 1, "universe": {**PINNED, "point_in_time": True}}
    assert result_differences(stored, fresh) == ["universe"]
    assert result_differences({"summary": 2}, fresh) == ["summary"]
