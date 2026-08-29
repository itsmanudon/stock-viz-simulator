from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlmodel import Session

from stockviz import __version__
from stockviz.db import get_session

router = APIRouter(tags=["health"])

SessionDep = Annotated[Session, Depends(get_session)]


class LiveResponse(BaseModel):
    status: Literal["ok"]


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    database: Literal["up", "down"]


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

    return HealthResponse(status=app_status, version=__version__, database=db_status)
