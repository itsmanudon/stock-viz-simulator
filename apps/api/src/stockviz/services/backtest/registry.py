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
    count = session.exec(
        select(func.count()).select_from(ExperimentRun).where(col(ExperimentRun.user_id) == user_id)
    ).one()
    if count >= MAX_RUNS_PER_USER:
        raise RunLimitReached(f"At most {MAX_RUNS_PER_USER} saved runs; delete some first")
    if experiment_id is not None:
        experiment = session.get(Experiment, experiment_id)
        if experiment is None or experiment.user_id != user_id:
            raise LookupError(f"Experiment {experiment_id} not found")
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


@dataclass
class RerunReport:
    status: str  # identical | different | data_changed
    stored_fingerprint: str
    current_fingerprint: str
    differences: list[str] = field(default_factory=list)


def rerun(session: Session, row: ExperimentRun) -> RerunReport:
    body = BacktestIn.model_validate(row.request)
    run = execute_backtest(session, body)
    if run.fingerprint != row.dataset_fingerprint:
        return RerunReport("data_changed", row.dataset_fingerprint, run.fingerprint)
    fresh = _result(run)
    differences = sorted(
        k for k in set(fresh) | set(row.result) if fresh.get(k) != row.result.get(k)
    )
    return RerunReport(
        "identical" if not differences else "different",
        row.dataset_fingerprint,
        run.fingerprint,
        differences,
    )
