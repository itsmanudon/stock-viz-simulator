"""Shared pytest fixtures.

The DB-backed tests use a fresh SQLite in-memory engine per test. The FastAPI
app's ``get_session`` dependency is overridden so the TestClient sees that
engine. This keeps tests fast and self-contained — no Postgres required.

The ingest writer (which uses Postgres-specific ``ON CONFLICT``) isn't exercised
here; its smoke test runs against the docker-compose Postgres in CI / local dev.
"""

from __future__ import annotations

import os

os.environ.setdefault("RATELIMIT_ENABLED", "0")

from collections.abc import Generator, Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

# Import the models module to register tables on SQLModel.metadata before
# ``create_all`` runs. The ``noqa`` suppresses the unused-import lint.
import stockviz.models  # noqa: F401
from stockviz.db import get_session
from stockviz.main import app


@pytest.fixture
def engine():
    """A throwaway in-memory SQLite engine with all tables created."""
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,  # share one connection across the test
    )
    SQLModel.metadata.create_all(eng)
    try:
        yield eng
    finally:
        eng.dispose()


@pytest.fixture
def session(engine) -> Generator[Session, None, None]:
    with Session(engine) as s:
        yield s


@pytest.fixture
def client(session: Session) -> Iterator[TestClient]:
    """TestClient with ``get_session`` overridden to the test session."""

    def _override() -> Iterator[Session]:
        yield session

    app.dependency_overrides[get_session] = _override
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _orders_placed_before_seeded_bars(request, monkeypatch):
    """Let settlement tests fill orders placed "now" against seeded 2025 bars.

    LG-5 fills an order only on a session that closed after it was placed.
    Most settlement tests seed bars dated 2025 and place orders at the wall
    clock, and they test other things (kernel parity, reservations, FX), so
    the placement check is off for them. Tests of the rule itself carry
    ``@pytest.mark.placement_guard`` and run it for real.
    """
    if request.node.get_closest_marker("placement_guard") is None:
        from datetime import date

        monkeypatch.setattr(
            "stockviz.services.trading.orders._known_at_placement", lambda _order: date.min
        )
