"""`/v1/status` — what the nightly run left behind (audit OP-5, Phase 7.6).

Public (owner's choice for Phase 7): job names, times and states only. No
error text, no counts of users or money. The web `/status` page reads it.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import func
from sqlmodel import Session, col, select

from stockviz.db import get_session
from stockviz.limiter import limiter
from stockviz.models import AegisSyncRun, Instrument, JobRun, OutboxEvent, PriceBar

router = APIRouter(prefix="/v1", tags=["status"])

SessionDep = Annotated[Session, Depends(get_session)]


class JobStatusOut(BaseModel):
    job: str
    status: str
    started_at: datetime
    finished_at: datetime | None
    last_success_at: datetime | None


class MarketStatusOut(BaseModel):
    country: str
    newest_bar: date | None


class StatusOut(BaseModel):
    jobs: list[JobStatusOut]
    aegis_sync_status: str | None
    aegis_sync_finished_at: datetime | None
    markets: list[MarketStatusOut]
    dead_outbox_events: int


@router.get("/status", response_model=StatusOut)
@limiter.limit("30/minute")
def status(request: Request, session: SessionDep) -> StatusOut:
    latest_ids = select(func.max(JobRun.id)).group_by(col(JobRun.job))
    latest = session.exec(
        select(JobRun).where(col(JobRun.id).in_(latest_ids)).order_by(col(JobRun.job))
    ).all()
    successes = dict(
        session.exec(
            select(col(JobRun.job), func.max(JobRun.finished_at))
            .where(JobRun.status == "succeeded")
            .group_by(col(JobRun.job))
        ).all()
    )
    sync = session.exec(select(AegisSyncRun).order_by(col(AegisSyncRun.id).desc()).limit(1)).first()
    markets = session.exec(
        select(col(Instrument.country), func.max(PriceBar.ts))
        .join(PriceBar, col(PriceBar.instrument_id) == col(Instrument.id))
        .where(PriceBar.interval == "1d", col(Instrument.country).is_not(None))
        .group_by(col(Instrument.country))
        .order_by(col(Instrument.country))
    ).all()
    dead = session.exec(
        select(func.count()).select_from(OutboxEvent).where(col(OutboxEvent.dead_at).is_not(None))  # type: ignore[call-overload]
    ).one()
    return StatusOut(
        jobs=[
            JobStatusOut(
                job=run.job,
                status=run.status,
                started_at=run.started_at,
                finished_at=run.finished_at,
                last_success_at=successes.get(run.job),
            )
            for run in latest
        ],
        aegis_sync_status=sync.status if sync else None,
        aegis_sync_finished_at=sync.finished_at if sync else None,
        markets=[
            MarketStatusOut(country=country or "", newest_bar=ts.date() if ts else None)
            for country, ts in markets
        ],
        dead_outbox_events=int(dead or 0),
    )
