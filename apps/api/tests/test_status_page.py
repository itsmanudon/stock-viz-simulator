"""`/v1/status` (audit OP-5, Phase 7.6): public, names and times only."""

from __future__ import annotations

from datetime import datetime

from fastapi.testclient import TestClient
from sqlmodel import Session

from stockviz.models import JobRun
from tests.symbols import seed_symbols


def test_status_lists_each_jobs_latest_run_without_error_text(
    session: Session, client: TestClient
) -> None:
    seed_symbols(session, "AAPL")
    session.add_all(
        [
            JobRun(job="ingest", status="succeeded", started_at=datetime(2026, 11, 11, 22),
                   finished_at=datetime(2026, 11, 11, 22, 20)),
            JobRun(job="ingest", status="failed", started_at=datetime(2026, 11, 12, 22),
                   finished_at=datetime(2026, 11, 12, 22, 5), error="secret-looking stack"),
            JobRun(job="fx", status="skipped", started_at=datetime(2026, 11, 12, 22, 6)),
        ]
    )  # fmt: skip
    session.commit()
    res = client.get("/v1/status")
    assert res.status_code == 200
    body = res.json()
    jobs = {j["job"]: j for j in body["jobs"]}
    assert jobs["ingest"]["status"] == "failed"
    assert jobs["ingest"]["last_success_at"].startswith("2026-11-11T22:20")
    assert jobs["fx"]["status"] == "skipped" and jobs["fx"]["last_success_at"] is None
    assert "secret-looking" not in res.text and "error" not in res.text
    assert body["dead_outbox_events"] == 0 and body["aegis_sync_status"] is None
