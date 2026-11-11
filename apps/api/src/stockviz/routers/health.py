import logging
from datetime import date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel
from sqlalchemy import func, text
from sqlmodel import Session, select

from stockviz import __version__
from stockviz.db import get_session

router = APIRouter(tags=["health"])
logger = logging.getLogger(__name__)

SessionDep = Annotated[Session, Depends(get_session)]


class LiveResponse(BaseModel):
    status: Literal["ok"]


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    database: Literal["up", "down"]
    # What the nightly job left behind (audit OP-5). Informational: status
    # depends on the database only, so a stale night never fails a deploy's
    # health check. None when unknown (no rows, or the table is not there yet).
    newest_bar: date | None = None
    last_job_success_at: datetime | None = None
    # Jobs whose most recent run failed.
    failing_jobs: list[str] = []


@router.get("/live", response_model=LiveResponse)
def live() -> LiveResponse:
    """Process liveness. Does not touch PostgreSQL, Kafka, or providers.

    Kubernetes should probe this for ``livenessProbe``. A database outage
    must not restart a healthy API process — that is what ``/health`` is for.
    """
    return LiveResponse(status="ok")


@router.get("/health", response_model=HealthResponse)
def health(session: SessionDep, response: Response) -> HealthResponse:
    """Readiness + DB reachability.

    Returns **503** when the database is unreachable. ``render.yaml`` points
    ``healthCheckPath`` here, and a always-200 response meant Render would
    never notice — let alone restart — an instance that had lost its database.

    Kubernetes should probe this for ``readinessProbe`` so pods drop out of
    the Service while Postgres is gone, without being killed.
    """
    try:
        session.exec(text("SELECT 1"))  # type: ignore[arg-type]
        db_status: Literal["up", "down"] = "up"
        app_status: Literal["ok", "degraded"] = "ok"
    except Exception:
        db_status = "down"
        app_status = "degraded"
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    out = HealthResponse(status=app_status, version=__version__, database=db_status)
    if db_status == "up":
        _add_nightly_state(session, out)
    return out


def _add_nightly_state(session: Session, out: HealthResponse) -> None:
    """Fill the OP-5 fields. Any failure leaves them empty, never fails /health."""
    from stockviz.models import JobRun, PriceBar

    try:
        newest = session.exec(
            select(func.max(PriceBar.ts)).where(PriceBar.interval == "1d")  # type: ignore[call-overload]
        ).one()
        out.newest_bar = newest.date() if newest is not None else None
        out.last_job_success_at = session.exec(
            select(func.max(JobRun.finished_at)).where(JobRun.status == "succeeded")  # type: ignore[call-overload]
        ).one()
        latest_per_job = (
            select(JobRun.job, func.max(JobRun.id).label("latest_id"))
            .group_by(JobRun.job)  # type: ignore[arg-type]
            .subquery()
        )
        out.failing_jobs = sorted(
            session.exec(
                select(JobRun.job)
                .join(latest_per_job, JobRun.id == latest_per_job.c.latest_id)  # type: ignore[arg-type]
                .where(JobRun.status == "failed")
            ).all()
        )
    except Exception:
        session.rollback()
        logger.exception("health: could not read the nightly job state")
