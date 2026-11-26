"""Broker status and graceful degradation (A5.7, M1.7).

StockViz has no live broker connection. Kite Connect (Zerodha) is a
**snapshot** provider: the owner logs in by hand and runs
``stockviz.cli ingest-history --provider kite`` for a one-off history pull,
and the day's access token lives only in that process's memory. There is no
login route, no callback and no token table (the daily login is deferred to
A6: it needs a paid Kite Connect app). Imported books update only from an
uploaded tradebook (CSV, A5.3).

This module answers "what can the app do with each broker right now" so the
web can say it in plain words instead of failing:

- ``not_configured``: ``KITE_API_KEY`` or ``KITE_API_SECRET`` is blank, so
  Kite is off on this server.
- ``offline``: the newest Kite snapshot run failed with a provider error
  within ``OFFLINE_WINDOW``.
- ``snapshot_only``: configured, and a snapshot has succeeded; Kite only
  serves one-off history pulls.
- ``not_connected``: configured, and no snapshot has run yet (or the last
  failure is older than the window).

Provider health is read from ``job_runs`` (OP-5): the Kite path of
``ingest-history`` writes one row per attempt under ``KITE_SNAPSHOT_JOB``
through ``record_provider_run``. The row never holds a token, a key or Kite's
message text, only a fixed summary.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from sqlmodel import Session, col, func, select

from stockviz._time import utcnow
from stockviz.models import BookKind, JobRun, Portfolio
from stockviz.settings import Settings

BrokerState = Literal["not_configured", "not_connected", "offline", "snapshot_only"]

KITE_SNAPSHOT_JOB = "kite-snapshot"
"""``job_runs.job`` for each Kite history snapshot attempt."""

FEED_BACKFILL_JOBS = {name: f"intraday-backfill-{name}" for name in ("alpaca", "tiingo", "massive")}
"""A6.3: ``job_runs.job`` for each ``intraday-backfill --apply`` run, per provider."""

MANUAL_PROVIDER_JOBS = (KITE_SNAPSHOT_JOB, *FEED_BACKFILL_JOBS.values())
"""By-hand provider runs: ``/v1/status`` and ``/health`` leave them out (not nightly)."""

OFFLINE_WINDOW = timedelta(days=3)
"""How long a failed Kite run keeps the broker ``offline``."""


@dataclass(frozen=True)
class BrokerStatus:
    broker: str
    label: str
    provider: str
    configured: bool
    state: BrokerState
    imported_books: int
    last_imported_at: datetime | None
    last_snapshot_at: datetime | None
    last_failure_at: datetime | None


def kite_configured(settings: Settings) -> bool:
    """Both halves of the Kite app are set (the snapshot needs both)."""
    return bool(settings.kite_api_key.strip() and settings.kite_api_secret.strip())


def record_provider_run(
    session: Session, job: str, *, ok: bool, summary: str | None = None
) -> JobRun:
    """Write one finished provider run to ``job_runs``.

    ``summary`` is a fixed, short description chosen by the caller (for
    example "Kite login failed"), never a provider message, URL or token.
    """
    now = utcnow()
    row = JobRun(
        job=job,
        started_at=now,
        finished_at=now,
        status="succeeded" if ok else "failed",
        exit_code=0 if ok else 1,
        error=None if ok else (summary or "provider error")[:200],
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def _kite_state(
    session: Session, settings: Settings, now: datetime
) -> tuple[BrokerState, datetime | None, datetime | None]:
    last_ok = session.exec(
        select(func.max(JobRun.finished_at)).where(
            JobRun.job == KITE_SNAPSHOT_JOB, JobRun.status == "succeeded"
        )
    ).one()
    last_failed = session.exec(
        select(func.max(JobRun.finished_at)).where(
            JobRun.job == KITE_SNAPSHOT_JOB, JobRun.status == "failed"
        )
    ).one()
    if not kite_configured(settings):
        return "not_configured", last_ok, last_failed
    failing = last_failed is not None and (last_ok is None or last_failed > last_ok)
    if failing and last_failed is not None and now - last_failed <= OFFLINE_WINDOW:
        return "offline", last_ok, last_failed
    if last_ok is not None:
        return "snapshot_only", last_ok, last_failed
    return "not_connected", last_ok, last_failed


def broker_statuses(
    session: Session, settings: Settings, user_id: int, *, now: datetime | None = None
) -> list[BrokerStatus]:
    """Every broker the app knows, for one user. Zerodha (Kite) only today."""
    state, last_ok, last_failed = _kite_state(session, settings, now or utcnow())
    imported = session.exec(
        select(func.count())
        .select_from(Portfolio)
        .where(
            Portfolio.user_id == user_id,
            Portfolio.kind == BookKind.IMPORTED,
            Portfolio.broker == "zerodha",
            col(Portfolio.archived_at).is_(None),
        )
    ).one()
    # A5.3: the newest committed tradebook upload into any of the caller's
    # Zerodha books (archived ones too: the upload still happened).
    from stockviz.models.broker_import import ImportBatch

    last_imported = session.exec(
        select(func.max(ImportBatch.created_at))
        .join(Portfolio, col(Portfolio.id) == col(ImportBatch.portfolio_id))
        .where(
            col(Portfolio.user_id) == user_id,
            col(Portfolio.broker) == "zerodha",
            col(ImportBatch.broker) == "zerodha",
        )
    ).one()
    return [
        BrokerStatus(
            broker="zerodha",
            label="Zerodha",
            provider="kite",
            configured=kite_configured(settings),
            state=state,
            imported_books=int(imported or 0),
            last_imported_at=last_imported,
            last_snapshot_at=last_ok,
            last_failure_at=last_failed,
        )
    ]
