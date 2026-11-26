"""The trial ledger, strategy families, the locked holdout and the checks (A4.3).

**Strategy family.** Variants of one idea on one universe, whatever their
numbers and dates:

- a template run: the template type and the ticker (``SMA crossover ·
  AAPL``), so every SMA window pair on AAPL is a variant;
- a rule strategy: the entry and exit rules' canonical text with every
  number replaced by ``#`` (``sma(close, 50) > sma(close, 200)`` and
  ``sma(close, 20) > sma(close, 100)`` are one family), which stops are
  used (fixed, ATR, trailing % or ATR, time; not their values), the sizing
  kind, the direction and the tickers;
- a rotation (A4.4): the ranking and cash filter skeletons, the weighting
  and the tickers (top N, buffer and the schedule are variants).

Dates, costs, fill rule and cash are not part of the family: trying another
range or cost is one more variant. A **variant** is a distinct strategy hash
(the strategy's own hash for rule strategies, SHA-256 of the whole request
for templates), so rerunning the same request does not add a trial.

**Privacy.** Rows are keyed by the signed-in user; anonymous runs share one
pool (``user_id`` NULL). Nothing identifying a visitor (address, cookie,
agent) is stored. A family's N counts the caller's own variants, or the
pool's for an anonymous caller. ``stockviz.cli prune-trials`` deletes rows
not run for ``--days`` (default 365); nothing schedules it.

**Locked holdout.** With ``holdout: last_20pct`` (the default) a run uses the
first 80% of the requested calendar days (``in_sample_days = total * 4 // 5``)
and the rest is held out. Sweeps and walk-forwards use the same in-sample
range. A signed-in user may unlock a family's holdout once; the time is
recorded and from then on every run of the family shows the holdout as
"seen", with its result.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import statistics
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from sqlmodel import Session, col, delete, select

from stockviz._time import utcnow
from stockviz.models import BacktestTrial, HoldoutUnlock
from stockviz.schemas import (
    BacktestIn,
    DsrOut,
    HoldoutResultOut,
    HoldoutStatusOut,
    OverfittingChecksOut,
    RotationBacktestOut,
    RunWindowOut,
    StrategyBacktestOut,
    TrialsOut,
)
from stockviz.services.backtest.engine import TRADING_DAYS_PER_YEAR
from stockviz.services.backtest.report import SharpeStats, deflated

HOLDOUT_PCT = 20.0
PRUNE_DAYS = 365

FAMILY_DEFINITION = (
    "A strategy family is one idea on one universe: the template type and ticker, or the "
    "rules with every number replaced by #, the stop kinds, the sizing kind, the direction "
    "and the tickers. Each distinct strategy hash in it (other numbers, dates or costs) is "
    "one variant."
)
DSR_FORMULA = (
    "SR0 = sqrt(V) x ((1 - g) x inv_Phi(1 - 1/N) + g x inv_Phi(1 - 1/(N e))), g = 0.5772; "
    "DSR = PSR(SR0) = Phi((SR - SR0) sqrt(T - 1) / sqrt(1 - skew SR + (kurt - 1)/4 SR^2)) "
    "(Bailey and Lopez de Prado, 2014)"
)

_NUMBER = re.compile(r"(?<![A-Za-z_0-9.])\d+(?:\.\d+)?(?![A-Za-z_0-9])")


@dataclass(frozen=True)
class Family:
    key: str
    label: str
    mode: str


def _sha(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def skeleton(canonical: str) -> str:
    """A rule's canonical text with its numbers as ``#``."""
    return _NUMBER.sub("#", canonical)


TEMPLATE_NAMES = {"sma_crossover": "SMA crossover", "rsi_threshold": "RSI threshold"}


def template_family(body: BacktestIn) -> Family:
    kind = body.strategy.type
    ticker = body.ticker.upper()
    return Family(
        _sha({"mode": "template", "type": kind, "ticker": ticker}),
        f"{TEMPLATE_NAMES.get(kind, kind)} · {ticker}",
        "template",
    )


def template_hash(body: BacktestIn) -> str:
    return _sha(body.model_dump(mode="json", by_alias=True))


def template_label(strategy: dict[str, Any] | Any) -> str:
    s = strategy if isinstance(strategy, dict) else strategy.model_dump(mode="json")
    if s.get("type") == "sma_crossover":
        return f"SMA {s['short_window']}/{s['long_window']}"
    return f"RSI < {s['buy_below']:g} buy, > {s['sell_above']:g} sell"


def _stop_kinds(out: StrategyBacktestOut) -> list[str]:
    s = out.stops
    kinds = []
    if s.fixed_pct is not None:
        kinds.append("fixed")
    if s.atr is not None:
        kinds.append("atr")
    if s.trailing is not None:
        kinds.append(f"trailing_{s.trailing.kind}")
    if s.time_bars is not None:
        kinds.append("time")
    return kinds


def strategy_family(out: StrategyBacktestOut) -> Family:
    rules = {r.role: skeleton(r.canonical) for r in out.rules}
    tickers = list(out.tickers)
    payload = {
        "mode": "strategy",
        "entry": rules.get("entry"),
        "exit": rules.get("exit"),
        "stops": _stop_kinds(out),
        "sizing": out.sizing.kind,
        "direction": out.direction,
        "tickers": tickers,
    }
    where = tickers[0] if len(tickers) == 1 else f"{tickers[0]} +{len(tickers) - 1}"
    return Family(_sha(payload), f"Rule strategy · {where}"[:120], "strategy")


def strategy_label(out: StrategyBacktestOut) -> str:
    parts = [f"{r.role}: {r.canonical}" for r in out.rules]
    return " | ".join(parts)[:200]


def rotation_family(out: RotationBacktestOut) -> Family:
    rules = {r.role: skeleton(r.canonical) for r in out.rules}
    tickers = list(out.tickers)
    payload = {
        "mode": "rotation",
        "ranking": rules.get("ranking"),
        "cash_filter": rules.get("cash_filter"),
        "weighting": out.weighting,
        "tickers": tickers,
    }
    where = f"{tickers[0]} +{len(tickers) - 1}" if len(tickers) > 1 else tickers[0]
    return Family(_sha(payload), f"Rotation · {where}"[:120], "rotation")


def rotation_label(out: RotationBacktestOut) -> str:
    parts = [f"{r.role}: {r.canonical}" for r in out.rules]
    head = f"top {out.top_n} {out.schedule} {out.weighting}"
    return " | ".join([head, *parts])[:200]


# --- the window ------------------------------------------------------------


def split_window(start: date, end: date, mode: str) -> RunWindowOut:
    """The in-sample range and the held-out tail for a requested range."""
    total = (end - start).days + 1
    if mode == "none":
        return RunWindowOut(
            requested_from=start, requested_to=end, from_date=start, to_date=end,
            holdout="none", note="No holdout: run on the whole range by explicit choice.",
        )  # fmt: skip
    inside = total * 4 // 5
    if total < 2 or inside < 1 or inside >= total:
        return RunWindowOut(
            requested_from=start, requested_to=end, from_date=start, to_date=end,
            holdout="last_20pct", holdout_pct=HOLDOUT_PCT,
            note="The range is too short to hold out its last 20%; the whole range was used.",
        )  # fmt: skip
    to = start + timedelta(days=inside - 1)
    return RunWindowOut(
        requested_from=start,
        requested_to=end,
        from_date=start,
        to_date=to,
        holdout="last_20pct",
        holdout_pct=HOLDOUT_PCT,
        holdout_from=to + timedelta(days=1),
        holdout_to=end,
        note=(
            f"In-sample: {start.isoformat()} to {to.isoformat()}. The last 20% "
            f"({(to + timedelta(days=1)).isoformat()} to {end.isoformat()}) is held out."
        ),
    )


# --- the ledger ------------------------------------------------------------


def record_trial(
    session: Session,
    *,
    user_id: int | None,
    family: Family,
    source: str,
    strategy_hash: str,
    fingerprint: str,
    label: str,
    stats: SharpeStats,
    total_return: float,
    commit: bool = True,
) -> None:
    """Add a variant to the ledger, or count one more run of it."""
    owner = (
        col(BacktestTrial.user_id).is_(None)
        if user_id is None
        else col(BacktestTrial.user_id) == user_id
    )
    row = session.exec(
        select(BacktestTrial).where(
            owner,
            col(BacktestTrial.strategy_hash) == strategy_hash,
            col(BacktestTrial.data_fingerprint) == fingerprint,
        )
    ).first()
    now = utcnow()
    if row is None:
        session.add(
            BacktestTrial(
                user_id=user_id,
                mode=family.mode,
                source=source,
                family_key=family.key,
                family_label=family.label,
                strategy_hash=strategy_hash,
                data_fingerprint=fingerprint,
                label=label[:200],
                observations=stats.observations,
                sharpe=stats.sharpe if math.isfinite(stats.sharpe) else 0.0,
                total_return=total_return,
                created_at=now,
                last_run_at=now,
            )
        )
    else:
        row.runs += 1
        row.last_run_at = now
        session.add(row)
    if commit:
        session.commit()
    else:
        session.flush()


def family_trials(session: Session, family_key: str, user_id: int | None) -> TrialsOut:
    owner = (
        col(BacktestTrial.user_id).is_(None)
        if user_id is None
        else col(BacktestTrial.user_id) == user_id
    )
    rows = session.exec(
        select(BacktestTrial)
        .where(col(BacktestTrial.family_key) == family_key, owner)
        .order_by(col(BacktestTrial.last_run_at), col(BacktestTrial.id))
    ).all()
    latest: dict[str, BacktestTrial] = {}
    for r in rows:
        latest[r.strategy_hash] = r
    sharpes = [r.sharpe for r in latest.values()]
    variance = statistics.variance(sharpes) if len(sharpes) >= 2 else None
    label = rows[-1].family_label if rows else ""
    root = math.sqrt(TRADING_DAYS_PER_YEAR)
    return TrialsOut(
        family_key=family_key,
        family_label=label,
        definition=FAMILY_DEFINITION,
        scope="anonymous" if user_id is None else "user",
        n=len(latest),
        runs=sum(r.runs for r in rows),
        sharpe_variance=variance,
        sharpe_annual_values=[round(x * root, 6) for x in sharpes[-50:]],
    )


def dsr_out(stats: SharpeStats, trials: TrialsOut) -> DsrOut:
    n = max(trials.n, 1)
    sr0, value = deflated(stats, n, trials.sharpe_variance)
    root = math.sqrt(TRADING_DAYS_PER_YEAR)
    if n == 1:
        note = (
            "One variant tried: there is no best-of-N to deflate, so DSR = PSR(0), the "
            "probability that the true Sharpe is above zero given this track's length, "
            "skewness and kurtosis."
        )
    elif not trials.sharpe_variance:
        note = f"{n} variants with the same Sharpe: no spread to deflate by, so DSR = PSR(0)."
    else:
        note = (
            f"Deflated for {n} variants: the best of {n} tries with no skill would be expected to "
            f"show an annualised Sharpe of {sr0 * root:.2f}, so that is the bar."
        )
    if value is None:
        meaning = "Not defined: too few daily returns, or no variation in them."
    else:
        meaning = (
            f"About a {value:.0%} chance that the true Sharpe is above "
            + ("zero" if n == 1 or not trials.sharpe_variance else "what luck alone would give")
            + (f", allowing for the {n} variants tried." if n > 1 else ".")
        )
    return DsrOut(
        n=n,
        sharpe=stats.sharpe,
        sharpe_annual=stats.sharpe_annual,
        observations=stats.observations,
        skewness=stats.skewness,
        kurtosis=stats.kurtosis,
        variance=trials.sharpe_variance,
        expected_max_sharpe=sr0,
        expected_max_sharpe_annual=sr0 * root,
        value=value,
        formula=DSR_FORMULA,
        note=note,
        meaning=meaning,
    )


# --- the holdout -----------------------------------------------------------


class AlreadyUnlocked(RuntimeError):
    pass


class NoHoldout(ValueError):
    pass


def unlock_of(session: Session, user_id: int, family_key: str) -> HoldoutUnlock | None:
    return session.exec(
        select(HoldoutUnlock).where(
            col(HoldoutUnlock.user_id) == user_id, col(HoldoutUnlock.family_key) == family_key
        )
    ).first()


def unlock(session: Session, user_id: int, family: Family, window: RunWindowOut) -> HoldoutUnlock:
    """Record the one-time unlock. Raises ``NoHoldout`` or ``AlreadyUnlocked``."""
    if window.holdout_from is None or window.holdout_to is None:
        raise NoHoldout("This run has no holdout to unlock")
    existing = unlock_of(session, user_id, family.key)
    if existing is not None:
        raise AlreadyUnlocked(
            f"The holdout of {family.label} was unlocked on "
            f"{existing.unlocked_at.isoformat(timespec='minutes')}; it is already seen"
        )
    row = HoldoutUnlock(
        user_id=user_id,
        family_key=family.key,
        family_label=family.label,
        holdout_from=window.holdout_from,
        holdout_to=window.holdout_to,
        unlocked_at=utcnow(),
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def holdout_status(
    session: Session,
    *,
    user_id: int | None,
    family: Family,
    window: RunWindowOut,
    result: Callable[[], HoldoutResultOut | None],
) -> HoldoutStatusOut:
    if window.holdout == "none":
        return HoldoutStatusOut(mode="none", status="none", note=window.note)
    if window.holdout_from is None:
        return HoldoutStatusOut(mode="last_20pct", status="none", note=window.note)
    base = {
        "mode": "last_20pct",
        "holdout_from": window.holdout_from,
        "holdout_to": window.holdout_to,
    }
    if user_id is None:
        return HoldoutStatusOut(
            **base, status="locked", can_unlock=False,
            note="Holdout locked. Sign in to unlock it, once, for this strategy family.",
        )  # fmt: skip
    row = unlock_of(session, user_id, family.key)
    if row is None:
        return HoldoutStatusOut(
            **base, status="locked", can_unlock=True,
            note=(
                "Holdout locked: sweeps and walk-forwards never see it. Unlock it once, when the "
                "family is final; after that every run of it shows the holdout as seen."
            ),
        )  # fmt: skip
    return HoldoutStatusOut(
        **base,
        status="seen",
        unlocked_at=row.unlocked_at,
        result=result(),
        note=(
            "Holdout seen: unlocked once for this family. Results on it are no longer out of "
            "sample for later variants of the family."
        ),
    )


def checks(
    session: Session,
    *,
    user_id: int | None,
    family: Family,
    stats: SharpeStats,
    window: RunWindowOut,
    holdout_result: Callable[[], HoldoutResultOut | None],
) -> OverfittingChecksOut:
    trials = family_trials(session, family.key, user_id)
    if not trials.family_label:
        trials = trials.model_copy(update={"family_label": family.label})
    return OverfittingChecksOut(
        trials=trials,
        dsr=dsr_out(stats, trials),
        holdout=holdout_status(
            session, user_id=user_id, family=family, window=window, result=holdout_result
        ),
    )


def prune_trials(session: Session, *, days: int = PRUNE_DAYS) -> int:
    cutoff = utcnow() - timedelta(days=days)
    result = session.exec(delete(BacktestTrial).where(col(BacktestTrial.last_run_at) < cutoff))  # type: ignore[call-overload]
    session.commit()
    return int(result.rowcount or 0)


__all__ = [
    "FAMILY_DEFINITION",
    "AlreadyUnlocked",
    "Family",
    "NoHoldout",
    "checks",
    "dsr_out",
    "family_trials",
    "holdout_status",
    "prune_trials",
    "record_trial",
    "skeleton",
    "split_window",
    "strategy_family",
    "strategy_label",
    "template_family",
    "template_hash",
    "template_label",
    "unlock",
]
