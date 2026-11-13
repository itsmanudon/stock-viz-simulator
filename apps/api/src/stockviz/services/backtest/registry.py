"""Saved backtests and identical reruns (Phase 5.4, the phase's acceptance).

``save_run`` runs a request through ``execute_backtest`` and stores the
request, kernel profile, fee schedule, code version, dataset fingerprint and
result. ``rerun`` loads the request, runs it again on today's data and:

- ``data_changed`` when the fingerprint differs (bars or dividends were
  added, rewritten or removed since): the results are not comparable, and
  nothing is claimed;
- ``identical`` when the fingerprint matches and the result is equal to the
  stored one, field for field (amounts as stored strings);
- ``different`` otherwise: same data, different answer, so the code changed
  how it computes. The differing top-level fields are listed.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from sqlmodel import Session, col, func, select

from stockviz.models import Experiment, ExperimentRun
from stockviz.schemas import BacktestIn
from stockviz.services.backtest.run import BacktestRun, execute_backtest
from stockviz.services.backtest.walkforward import Computed, sweep, walk_forward

MAX_RUNS_PER_USER = 500
"""A run stores its whole equity curve; this bounds one user's storage."""


class RunLimitReached(RuntimeError):
    pass


def code_version() -> str:
    """The deployed commit (Railway sets ``RAILWAY_GIT_COMMIT_SHA``), else ``unknown``."""
    return (os.environ.get("RAILWAY_GIT_COMMIT_SHA") or "unknown")[:64]


def _result(run: BacktestRun) -> dict[str, Any]:
    return run.out.model_dump(mode="json")


def save_run(
    session: Session,
    *,
    user_id: int,
    body: BacktestIn,
    experiment_id: int | None = None,
    parent_run_id: int | None = None,
    kind: str = "single",
) -> ExperimentRun:
    """Run ``body`` and store it. Commits. Raises ``RunLimitReached``."""
    _check_room(session, user_id, experiment_id)
    run = execute_backtest(session, body)
    row = ExperimentRun(
        user_id=user_id,
        experiment_id=experiment_id,
        parent_run_id=parent_run_id,
        kind=kind,
        ticker=run.out.ticker,
        request=body.model_dump(mode="json", by_alias=True),
        execution_profile=run.out.execution_profile,
        fee_schedule=run.out.fee_schedule,
        code_version=code_version(),
        dataset_fingerprint=run.fingerprint,
        bar_count=run.bar_count,
        first_bar_at=run.first_bar_at,
        last_bar_at=run.last_bar_at,
        result=_result(run),
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def _check_room(session: Session, user_id: int, experiment_id: int | None) -> None:
    count = session.exec(
        select(func.count()).select_from(ExperimentRun).where(col(ExperimentRun.user_id) == user_id)
    ).one()
    if count >= MAX_RUNS_PER_USER:
        raise RunLimitReached(f"At most {MAX_RUNS_PER_USER} saved runs; delete some first")
    if experiment_id is not None:
        experiment = session.get(Experiment, experiment_id)
        if experiment is None or experiment.user_id != user_id:
            raise LookupError(f"Experiment {experiment_id} not found")


def _compute(session: Session, kind: str, request: dict[str, Any]) -> Computed:
    body = BacktestIn.model_validate(request["backtest"])
    grid = request.get("grid")
    if kind == "walk_forward":
        return walk_forward(
            session,
            body,
            grid=grid,
            in_sample_years=request["in_sample_years"],
            out_of_sample_years=request["out_of_sample_years"],
            step_years=request["step_years"],
            score=request["score"],
        )
    return sweep(session, body, grid=grid, score=request["score"])


def save_study(
    session: Session,
    *,
    user_id: int,
    kind: str,
    request: dict[str, Any],
    experiment_id: int | None = None,
) -> ExperimentRun:
    """Run and store a walk-forward or sweep (Phase 5.5). Commits."""
    _check_room(session, user_id, experiment_id)
    computed = _compute(session, kind, request)
    body = BacktestIn.model_validate(request["backtest"])
    from stockviz.services.backtest.engine import FILL_RULES

    profile = FILL_RULES[body.fill_rule]
    row = ExperimentRun(
        user_id=user_id,
        experiment_id=experiment_id,
        kind=kind,
        ticker=body.ticker.upper(),
        request=request,
        execution_profile=f"{profile.name}/{profile.model_version}",
        fee_schedule=body.fee_schedule,
        code_version=code_version(),
        dataset_fingerprint=computed.fingerprint,
        bar_count=computed.bar_count,
        first_bar_at=computed.first_bar_at,
        last_bar_at=computed.last_bar_at,
        result=computed.result,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


@dataclass
class RerunReport:
    status: str  # identical | different | data_changed
    stored_fingerprint: str
    current_fingerprint: str
    differences: list[str] = field(default_factory=list)


def rerun(session: Session, row: ExperimentRun) -> RerunReport:
    if row.kind in ("walk_forward", "sweep"):
        computed = _compute(session, row.kind, row.request)
        current_fp, fresh = computed.fingerprint, computed.result
    else:
        run = execute_backtest(session, BacktestIn.model_validate(row.request))
        current_fp, fresh = run.fingerprint, _result(run)
    if current_fp != row.dataset_fingerprint:
        return RerunReport("data_changed", row.dataset_fingerprint, current_fp)
    run_fp = current_fp
    differences = sorted(
        k for k in set(fresh) | set(row.result) if fresh.get(k) != row.result.get(k)
    )
    return RerunReport(
        "identical" if not differences else "different",
        row.dataset_fingerprint,
        run_fp,
        differences,
    )
