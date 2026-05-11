from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlmodel import Session

from stockviz import __version__
from stockviz.db import get_session

router = APIRouter(tags=["health"])

SessionDep = Annotated[Session, Depends(get_session)]


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    database: Literal["up", "down"]


@router.get("/health", response_model=HealthResponse)
def health(session: SessionDep) -> HealthResponse:
    try:
        session.exec(text("SELECT 1"))  # type: ignore[arg-type]
        db_status: Literal["up", "down"] = "up"
        status: Literal["ok", "degraded"] = "ok"
    except Exception:
        db_status = "down"
        status = "degraded"

    return HealthResponse(status=status, version=__version__, database=db_status)
