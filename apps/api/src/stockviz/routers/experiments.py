"""`/v1/experiments` — the experiment registry (Phase 5.4).

Saved backtests per user. Saving runs the request on the server (the same
``execute_backtest`` as the public endpoint) and stores everything needed to
rerun it identically. All endpoints need ``UserIdDep``.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, col, func, select

from stockviz.auth import UserIdDep
from stockviz.db import get_session
from stockviz.models import Experiment, ExperimentRun
from stockviz.schemas import (
    BacktestSummaryOut,
    ExperimentIn,
    ExperimentOut,
    ExperimentRerunOut,
    ExperimentRunIn,
    ExperimentRunOut,
    SweepIn,
    WalkForwardIn,
)
from stockviz.services.backtest import BacktestError
from stockviz.services.backtest.registry import RunLimitReached, rerun, save_run, save_study
from stockviz.services.backtest.run import BadRange, UnknownSymbol

router = APIRouter(prefix="/v1/experiments", tags=["experiments"])

SessionDep = Annotated[Session, Depends(get_session)]


def _run_out(row: ExperimentRun, *, full: bool) -> ExperimentRunOut:
    assert row.id is not None
    return ExperimentRunOut(
        id=row.id,
        experiment_id=row.experiment_id,
        parent_run_id=row.parent_run_id,
        kind=row.kind,
        ticker=row.ticker,
        request=row.request,
        execution_profile=row.execution_profile,
        fee_schedule=row.fee_schedule,
        code_version=row.code_version,
        dataset_fingerprint=row.dataset_fingerprint,
        bar_count=row.bar_count,
        first_bar_at=row.first_bar_at,
        last_bar_at=row.last_bar_at,
        created_at=row.created_at,
        summary=BacktestSummaryOut.model_validate(row.result["summary"]),
        result=row.result if full else None,
    )


def _own_run(session: Session, run_id: int, user_id: int) -> ExperimentRun:
    row = session.get(ExperimentRun, run_id)
    if row is None or row.user_id != user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Run {run_id} not found")
    return row


@router.post("", response_model=ExperimentOut, status_code=status.HTTP_201_CREATED)
def create_experiment(body: ExperimentIn, session: SessionDep, user_id: UserIdDep) -> ExperimentOut:
    row = Experiment(user_id=user_id, name=body.name, hypothesis=body.hypothesis)
    session.add(row)
    session.commit()
    session.refresh(row)
    assert row.id is not None
    return ExperimentOut(
        id=row.id, name=row.name, hypothesis=row.hypothesis, created_at=row.created_at
    )


@router.get("", response_model=list[ExperimentOut])
def list_experiments(session: SessionDep, user_id: UserIdDep) -> list[ExperimentOut]:
    counts = dict(
        session.exec(
            select(ExperimentRun.experiment_id, func.count())
            .where(col(ExperimentRun.user_id) == user_id)
            .group_by(col(ExperimentRun.experiment_id))
        ).all()
    )
    rows = session.exec(
        select(Experiment)
        .where(col(Experiment.user_id) == user_id)
        .order_by(col(Experiment.created_at).desc())
    ).all()
    return [
        ExperimentOut(
            id=r.id,  # type: ignore[arg-type]
            name=r.name,
            hypothesis=r.hypothesis,
            created_at=r.created_at,
            run_count=counts.get(r.id, 0),
        )
        for r in rows
    ]


@router.post("/runs", response_model=ExperimentRunOut, status_code=status.HTTP_201_CREATED)
def post_run(body: ExperimentRunIn, session: SessionDep, user_id: UserIdDep) -> ExperimentRunOut:
    try:
        row = save_run(
            session, user_id=user_id, body=body.backtest, experiment_id=body.experiment_id
        )
    except UnknownSymbol as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except (BadRange, BacktestError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except RunLimitReached as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return _run_out(row, full=True)


def _study(
    session: Session, user_id: int, kind: str, request: dict, experiment_id: int | None
) -> ExperimentRunOut:
    try:
        row = save_study(
            session, user_id=user_id, kind=kind, request=request, experiment_id=experiment_id
        )
    except UnknownSymbol as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except (BadRange, BacktestError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except RunLimitReached as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return _run_out(row, full=True)


@router.post("/walk-forward", response_model=ExperimentRunOut, status_code=status.HTTP_201_CREATED)
def post_walk_forward(
    body: WalkForwardIn, session: SessionDep, user_id: UserIdDep
) -> ExperimentRunOut:
    """Phase 5.5: choose on each in-sample period, score on the next; stored."""
    request = body.model_dump(mode="json", by_alias=True, exclude={"experiment_id"})
    return _study(session, user_id, "walk_forward", request, body.experiment_id)


@router.post("/sweep", response_model=ExperimentRunOut, status_code=status.HTTP_201_CREATED)
def post_sweep(body: SweepIn, session: SessionDep, user_id: UserIdDep) -> ExperimentRunOut:
    """Phase 5.5: every setting over the whole range, ranked; stored."""
    request = body.model_dump(mode="json", by_alias=True, exclude={"experiment_id"})
    return _study(session, user_id, "sweep", request, body.experiment_id)


@router.get("/runs", response_model=list[ExperimentRunOut])
def list_runs(
    session: SessionDep, user_id: UserIdDep, experiment_id: int | None = None
) -> list[ExperimentRunOut]:
    stmt = select(ExperimentRun).where(col(ExperimentRun.user_id) == user_id)
    if experiment_id is not None:
        stmt = stmt.where(col(ExperimentRun.experiment_id) == experiment_id)
    rows = session.exec(stmt.order_by(col(ExperimentRun.created_at).desc()).limit(200)).all()
    return [_run_out(r, full=False) for r in rows]


@router.get("/runs/{run_id}", response_model=ExperimentRunOut)
def get_run(run_id: int, session: SessionDep, user_id: UserIdDep) -> ExperimentRunOut:
    return _run_out(_own_run(session, run_id, user_id), full=True)


@router.post("/runs/{run_id}/rerun", response_model=ExperimentRerunOut)
def post_rerun(run_id: int, session: SessionDep, user_id: UserIdDep) -> ExperimentRerunOut:
    row = _own_run(session, run_id, user_id)
    try:
        report = rerun(session, row)
    except (UnknownSymbol, BadRange, BacktestError) as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Cannot rerun: {exc}") from exc
    return ExperimentRerunOut(
        status=report.status,  # type: ignore[arg-type]
        stored_fingerprint=report.stored_fingerprint,
        current_fingerprint=report.current_fingerprint,
        differences=report.differences,
    )


@router.delete("/runs/{run_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_run(run_id: int, session: SessionDep, user_id: UserIdDep) -> None:
    row = _own_run(session, run_id, user_id)
    for child in session.exec(
        select(ExperimentRun).where(col(ExperimentRun.parent_run_id) == run_id)
    ).all():
        session.delete(child)
    session.delete(row)
    session.commit()
