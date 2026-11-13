"""The nightly job run log and what /health reports from it (audit OP-5)."""

from __future__ import annotations

import argparse
from datetime import datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, col, select

from stockviz import cli
from stockviz.models import JobRun, PriceBar
from tests.symbols import seed_symbols


@pytest.fixture(autouse=True)
def _symbols(session) -> None:
    seed_symbols(session, "AAPL")


@pytest.fixture
def recorded(engine, monkeypatch):
    monkeypatch.setattr(cli, "engine", engine)
    return engine


def _runs(engine) -> list[JobRun]:
    with Session(engine) as session:
        return list(session.exec(select(JobRun).order_by(col(JobRun.id))).all())


def test_a_job_is_recorded_with_its_outcome(recorded, monkeypatch) -> None:
    outcomes = iter([0, 1, 2])
    monkeypatch.setattr(cli, "_cmd_metrics", lambda _a: next(outcomes))
    for _ in range(3):
        cli.main(["metrics"])

    runs = _runs(recorded)
    assert [(r.job, r.status, r.exit_code) for r in runs] == [
        ("metrics", "succeeded", 0),
        ("metrics", "failed", 1),
        ("metrics", "skipped", 2),
    ]
    assert all(r.finished_at is not None for r in runs)


def test_a_job_that_raises_is_recorded_as_failed_and_still_raises(recorded, monkeypatch) -> None:
    def boom(_args: argparse.Namespace) -> int:
        raise RuntimeError("database went away")

    monkeypatch.setattr(cli, "_cmd_metrics", boom)
    with pytest.raises(RuntimeError):
        cli.main(["metrics"])
    (run,) = _runs(recorded)
    assert run.status == "failed"
    assert run.error == "RuntimeError: database went away"


def test_maintenance_commands_are_not_recorded(recorded, monkeypatch) -> None:
    monkeypatch.setattr(cli, "_cmd_seed", lambda _a: 0)
    assert cli.main(["seed"]) == 0
    assert _runs(recorded) == []


def test_recording_never_breaks_the_job(engine, monkeypatch) -> None:
    """With no job_runs table the job still runs and returns its own code."""
    JobRun.__table__.drop(engine)  # type: ignore[attr-defined]
    monkeypatch.setattr(cli, "engine", engine)
    monkeypatch.setattr(cli, "_cmd_metrics", lambda _a: 0)
    assert cli.main(["metrics"]) == 0


def test_health_reports_the_nightly_state(session: Session, client: TestClient) -> None:
    session.add(
        PriceBar(
            ticker="AAPL",
            ts=datetime(2026, 11, 11),
            interval="1d",
            open=Decimal(1),
            high=Decimal(1),
            low=Decimal(1),
            close=Decimal(1),
            volume=1,
            source="test",
        )
    )
    session.add_all(
        [
            JobRun(job="ingest", status="succeeded", finished_at=datetime(2026, 11, 11, 22, 5)),
            JobRun(
                job="fx", status="failed", exit_code=1, finished_at=datetime(2026, 11, 11, 22, 6)
            ),
            JobRun(job="metrics", status="failed", exit_code=1),
            # metrics recovered on its next run, so it is not failing any more.
            JobRun(job="metrics", status="succeeded", finished_at=datetime(2026, 11, 11, 22, 9)),
        ]
    )
    session.commit()

    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["newest_bar"] == "2026-11-11"
    assert body["last_job_success_at"].startswith("2026-11-11T22:09")
    assert body["failing_jobs"] == ["fx"]


def test_health_is_ok_with_no_history(client: TestClient) -> None:
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["newest_bar"] is None and body["failing_jobs"] == []
