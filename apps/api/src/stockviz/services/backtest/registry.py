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
from stockviz.schemas import BacktestIn, StrategyBacktestIn
from stockviz.services.backtest.run import BacktestRun, execute_backtest
from stockviz.services.backtest.strategy_run import (
    execute_strategy,
    materialize_rules,
    request_json,
)
from stockviz.services.backtest.walkforward import Computed, sweep, walk_forward
from stockviz.services.fee_view import resolve_fee_schedule

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


def save_strategy_run(
    session: Session,
    *,
    user_id: int,
    body: StrategyBacktestIn,
    experiment_id: int | None = None,
) -> ExperimentRun:
    """A4.1: run a Rule DSL strategy and store it (``kind`` ``strategy``).
    Inline rules are saved as setup versions first, so the stored request
    names versions and its rerun reads the same immutable rules. Commits."""
    _check_room(session, user_id, experiment_id)
    execute_strategy(session, body, user_id=user_id)  # refuse before writing a version
    body = materialize_rules(session, body, user_id)
    run = execute_strategy(session, body, user_id=user_id)
    row = ExperimentRun(
        user_id=user_id,
        experiment_id=experiment_id,
        kind="strategy",
        ticker=run.label,
        request=request_json(body),
        execution_profile=run.out.execution_profile,
        fee_schedule=run.out.fee_schedule,
        code_version=code_version(),
        dataset_fingerprint=run.fingerprint,
        bar_count=run.bar_count,
        first_bar_at=run.first_bar_at,
        last_bar_at=run.last_bar_at,
        result=run.out.model_dump(mode="json"),
        setup_version_id=run.entry_version_id,
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


def as_saved(request: dict[str, Any]) -> dict[str, Any]:
    """A stored request as it ran. A4.2 added the ADV cap with a 10% default;
    a request saved before then has no ``adv_cap_pct`` and ran uncapped, so it
    reruns uncapped. (Its ``fee_schedule`` was always stored by name; the new
    ``auto`` default never applies to it.)"""
    if "adv_cap_pct" in request:
        return request
    return {**request, "adv_cap_pct": None}


def _compute(session: Session, kind: str, request: dict[str, Any]) -> Computed:
    request = {**request, "backtest": as_saved(request["backtest"])}
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
        fee_schedule=resolve_fee_schedule(body.fee_schedule, body.ticker.upper()),
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


STAMPS_ADDED_LATER = frozenset(
    {
        "universe",
        # A4.2: the costs disclosure and liquidity stamp, the template
        # summary's gross figures, and per-trade liquidity fields.
        "costs",
        "liquidity",
        "gross_return",
        "gross_final_nav",
        "total_fees",
        "price_costs",
        "requested_shares",
        "requested_quantity",
        "exit_adv_pct",
    }
)
"""Result fields added after runs were first stored (A1.4a, A4.2), at any
depth. A stored result that lacks one is not "different" for it: the field
describes the run or restates its figures, it is not a figure the code
recomputed differently. Everything the stored result does hold is compared."""


def _strip_added(stored: Any, fresh: Any) -> Any:
    if isinstance(stored, dict) and isinstance(fresh, dict):
        return {
            k: _strip_added(stored.get(k), v)
            for k, v in fresh.items()
            if k in stored or k not in STAMPS_ADDED_LATER
        }
    if isinstance(stored, list) and isinstance(fresh, list) and len(stored) == len(fresh):
        return [_strip_added(a, b) for a, b in zip(stored, fresh, strict=True)]
    return fresh


def result_differences(stored: dict[str, Any], fresh: dict[str, Any]) -> list[str]:
    """Top-level fields whose values differ, skipping later stamps the stored
    result never had."""
    fresh = _strip_added(stored, fresh)
    return sorted(k for k in set(fresh) | set(stored) if fresh.get(k) != stored.get(k))


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
    elif row.kind == "strategy":
        body = StrategyBacktestIn.model_validate(as_saved(row.request))
        strategy = execute_strategy(session, body, user_id=row.user_id)
        current_fp, fresh = strategy.fingerprint, strategy.out.model_dump(mode="json")
    else:
        run = execute_backtest(session, BacktestIn.model_validate(as_saved(row.request)))
        current_fp, fresh = run.fingerprint, _result(run)
    if current_fp != row.dataset_fingerprint:
        return RerunReport("data_changed", row.dataset_fingerprint, current_fp)
    run_fp = current_fp
    differences = result_differences(row.result, fresh)
    return RerunReport(
        "identical" if not differences else "different",
        row.dataset_fingerprint,
        run_fp,
        differences,
    )
