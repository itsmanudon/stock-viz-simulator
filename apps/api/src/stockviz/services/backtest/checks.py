"""Record a run in the trial ledger and read its overfitting checks (A4.3).

The routers and the registry call these after a run: the run's result never
depends on the ledger (the checks are attached to the response only), so a
saved run still reruns ``identical`` however many trials were recorded since.
"""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from typing import Any

from sqlmodel import Session

from stockviz.models import ExperimentRun
from stockviz.schemas import (
    BacktestIn,
    HoldoutResultOut,
    OverfittingChecksOut,
    RotationBacktestIn,
    RotationBacktestOut,
    RunWindowOut,
    StrategyBacktestIn,
    StrategyBacktestOut,
)
from stockviz.services.backtest import report, report_card, trials
from stockviz.services.backtest.rotation_run import RotationRun, execute_rotation
from stockviz.services.backtest.run import BacktestRun, execute_backtest
from stockviz.services.backtest.strategy_run import StrategyRun, execute_strategy


def _stats_of(navs: list[Decimal]) -> report.SharpeStats:
    return report.sharpe_stats(report.nav_returns(navs))


def _template_holdout(
    session: Session, body: BacktestIn, window: RunWindowOut
) -> Callable[[], HoldoutResultOut | None]:
    def run() -> HoldoutResultOut | None:
        if window.holdout_from is None or window.holdout_to is None:
            return None
        held = body.model_copy(update={"from_": window.holdout_from, "holdout": "none"})
        try:
            out = execute_backtest(session, held).out
        except Exception:  # no bars, or the symbol went away: nothing to show
            return None
        return report_card.holdout_result(
            start=window.holdout_from,
            end=window.holdout_to,
            total_return=out.summary.total_return,
            sharpe=out.summary.sharpe,
            max_drawdown=out.summary.max_drawdown,
            navs=[p.nav for p in out.equity_curve],
            trades=len(out.trades),
        )

    return run


def _strategy_holdout(
    session: Session, body: StrategyBacktestIn, window: RunWindowOut, user_id: int | None
) -> Callable[[], HoldoutResultOut | None]:
    def run() -> HoldoutResultOut | None:
        if window.holdout_from is None or window.holdout_to is None:
            return None
        held = body.model_copy(update={"from_": window.holdout_from, "holdout": "none"})
        try:
            out = execute_strategy(session, held, user_id=user_id).out
        except Exception:
            return None
        return report_card.holdout_result(
            start=window.holdout_from,
            end=window.holdout_to,
            total_return=out.summary.total_return,
            sharpe=out.summary.sharpe,
            max_drawdown=out.summary.max_drawdown,
            navs=[p.nav for p in out.equity_curve],
            trades=len(out.trades),
        )

    return run


def _rotation_holdout(
    session: Session, body: RotationBacktestIn, window: RunWindowOut, user_id: int | None
) -> Callable[[], HoldoutResultOut | None]:
    def run() -> HoldoutResultOut | None:
        if window.holdout_from is None or window.holdout_to is None:
            return None
        held = body.model_copy(update={"from_": window.holdout_from, "holdout": "none"})
        try:
            out = execute_rotation(session, held, user_id=user_id).out
        except Exception:
            return None
        return report_card.holdout_result(
            start=window.holdout_from,
            end=window.holdout_to,
            total_return=out.summary.total_return,
            sharpe=out.summary.sharpe,
            max_drawdown=out.summary.max_drawdown,
            navs=[p.nav for p in out.equity_curve],
            trades=len(out.trades),
        )

    return run


def template_checks(
    session: Session,
    body: BacktestIn,
    run: BacktestRun,
    *,
    user_id: int | None,
    source: str | None,
    read: bool = True,
) -> OverfittingChecksOut | None:
    """Record the run (when ``source`` is given) and return its checks
    (``read=False``: record only)."""
    family = trials.template_family(body)
    stats = run.stats or _stats_of([p.nav for p in run.out.equity_curve])
    if source is not None:
        trials.record_trial(
            session,
            user_id=user_id,
            family=family,
            source=source,
            strategy_hash=trials.template_hash(body),
            fingerprint=run.fingerprint,
            label=trials.template_label(body.strategy),
            stats=stats,
            total_return=run.out.summary.total_return,
        )
    if not read:
        return None
    window = run.out.window or trials.split_window(body.from_, body.to, body.holdout)
    return trials.checks(
        session,
        user_id=user_id,
        family=family,
        stats=stats,
        window=window,
        holdout_result=_template_holdout(session, body, window),
    )


def strategy_checks(
    session: Session,
    body: StrategyBacktestIn,
    run: StrategyRun,
    *,
    user_id: int | None,
    source: str | None,
    read: bool = True,
) -> OverfittingChecksOut | None:
    out = run.out
    family = trials.strategy_family(out)
    stats = run.stats or _stats_of([p.nav for p in out.equity_curve])
    if source is not None:
        trials.record_trial(
            session,
            user_id=user_id,
            family=family,
            source=source,
            strategy_hash=out.strategy_hash,
            fingerprint=run.fingerprint,
            label=trials.strategy_label(out),
            stats=stats,
            total_return=out.summary.total_return,
        )
    if not read:
        return None
    window = out.window or trials.split_window(body.from_, body.to, body.holdout)
    return trials.checks(
        session,
        user_id=user_id,
        family=family,
        stats=stats,
        window=window,
        holdout_result=_strategy_holdout(session, body, window, user_id),
    )


def rotation_checks(
    session: Session,
    body: RotationBacktestIn,
    run: RotationRun,
    *,
    user_id: int | None,
    source: str | None,
    read: bool = True,
) -> OverfittingChecksOut | None:
    """A4.4: the rotation's trial and checks, like a rule strategy's."""
    out = run.out
    family = trials.rotation_family(out)
    stats = run.stats or _stats_of([p.nav for p in out.equity_curve])
    if source is not None:
        trials.record_trial(
            session,
            user_id=user_id,
            family=family,
            source=source,
            strategy_hash=out.strategy_hash,
            fingerprint=run.fingerprint,
            label=trials.rotation_label(out),
            stats=stats,
            total_return=out.summary.total_return,
        )
    if not read:
        return None
    window = out.window or trials.split_window(body.from_, body.to, body.holdout)
    return trials.checks(
        session,
        user_id=user_id,
        family=family,
        stats=stats,
        window=window,
        holdout_result=_rotation_holdout(session, body, window, user_id),
    )


def record_members(
    session: Session, *, user_id: int, kind: str, members: list[Any], fingerprint: str
) -> None:
    """Each setting a sweep or walk-forward tried is a trial (one commit)."""
    for m in members:
        trials.record_trial(
            session,
            user_id=user_id,
            family=trials.template_family(m.spec),
            source=kind,
            strategy_hash=trials.template_hash(m.spec),
            fingerprint=fingerprint,
            label=trials.template_label(m.spec.strategy),
            stats=m.stats,
            total_return=m.total_return,
            commit=False,
        )
    session.commit()


def _window_of(result: dict[str, Any], start, end, mode: str) -> RunWindowOut:
    if result.get("window"):
        return RunWindowOut.model_validate(result["window"])
    return trials.split_window(start, end, mode)


def stored_checks(session: Session, row: ExperimentRun) -> OverfittingChecksOut | None:
    """The checks for a saved single or strategy run, read now from the ledger."""
    from stockviz.services.backtest.registry import as_saved

    result = row.result
    navs = [Decimal(str(p["nav"])) for p in result.get("equity_curve", [])]
    stats = _stats_of(navs)
    if row.kind == "single":
        body = BacktestIn.model_validate(as_saved(row.request))
        window = _window_of(result, body.from_, body.to, body.holdout)
        return trials.checks(
            session,
            user_id=row.user_id,
            family=trials.template_family(body),
            stats=stats,
            window=window,
            holdout_result=_template_holdout(session, body, window),
        )
    if row.kind == "strategy":
        body = StrategyBacktestIn.model_validate(as_saved(row.request))
        out = StrategyBacktestOut.model_validate(result)
        window = _window_of(result, body.from_, body.to, body.holdout)
        return trials.checks(
            session,
            user_id=row.user_id,
            family=trials.strategy_family(out),
            stats=stats,
            window=window,
            holdout_result=_strategy_holdout(session, body, window, row.user_id),
        )
    if row.kind == "rotation":
        body = RotationBacktestIn.model_validate(row.request)
        out = RotationBacktestOut.model_validate(result)
        window = _window_of(result, body.from_, body.to, body.holdout)
        return trials.checks(
            session,
            user_id=row.user_id,
            family=trials.rotation_family(out),
            stats=stats,
            window=window,
            holdout_result=_rotation_holdout(session, body, window, row.user_id),
        )
    return None


def unlock_family(
    session: Session,
    *,
    user_id: int,
    backtest: BacktestIn | None,
    strategy: StrategyBacktestIn | None,
    rotation: RotationBacktestIn | None = None,
) -> OverfittingChecksOut:
    """The one-time unlock: run it, record the unlock, return the checks with
    the holdout's result. Raises ``trials.NoHoldout`` / ``AlreadyUnlocked``
    and the run's own errors."""
    if backtest is not None:
        run = execute_backtest(session, backtest)
        window = run.out.window or trials.split_window(
            backtest.from_, backtest.to, backtest.holdout
        )
        trials.unlock(session, user_id, trials.template_family(backtest), window)
        checked = template_checks(session, backtest, run, user_id=user_id, source=None)
        assert checked is not None
        return checked
    if rotation is not None:
        rrun = execute_rotation(session, rotation, user_id=user_id)
        window = rrun.out.window or trials.split_window(
            rotation.from_, rotation.to, rotation.holdout
        )
        trials.unlock(session, user_id, trials.rotation_family(rrun.out), window)
        checked = rotation_checks(session, rotation, rrun, user_id=user_id, source=None)
        assert checked is not None
        return checked
    assert strategy is not None
    srun = execute_strategy(session, strategy, user_id=user_id)
    window = srun.out.window or trials.split_window(strategy.from_, strategy.to, strategy.holdout)
    trials.unlock(session, user_id, trials.strategy_family(srun.out), window)
    checked = strategy_checks(session, strategy, srun, user_id=user_id, source=None)
    assert checked is not None
    return checked


__all__ = [
    "record_members",
    "rotation_checks",
    "stored_checks",
    "strategy_checks",
    "template_checks",
    "unlock_family",
]
