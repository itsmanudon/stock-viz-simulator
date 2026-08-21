"""Tests for GET /health.

``render.yaml`` points ``healthCheckPath`` here, so the status code is the
contract: 200 means "route traffic to me", 503 means "this instance has lost
its database". It previously returned 200 even while reporting
``database: "down"``, which meant Render could never detect — let alone
restart — a broken instance.

These use dependency overrides rather than whatever database happens to be
reachable, so both branches are exercised deterministically.
"""

from __future__ import annotations

from collections.abc import Iterator

from fastapi.testclient import TestClient
from sqlmodel import Session

from stockviz.db import get_session
from stockviz.main import app


def test_health_reports_ok_when_the_database_answers(session: Session, client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "up"
    assert body["version"]


def test_health_reports_503_when_the_database_is_unreachable() -> None:
    """A degraded instance must fail its health check, not quietly report 200."""

    class _BrokenSession:
        def exec(self, *_args, **_kwargs):
            raise RuntimeError("connection refused")

    def _override() -> Iterator[object]:
        yield _BrokenSession()

    app.dependency_overrides[get_session] = _override
    try:
        with TestClient(app) as broken_client:
            response = broken_client.get("/health")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["database"] == "down"
    # Still a well-formed body — the orchestrator gets a reason, not a stack trace.
    assert body["version"]
