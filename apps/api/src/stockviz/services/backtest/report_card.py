"""Build a run's report card (A4.3): the pure metrics plus the regime split,
which reads index and breadth history from the database."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, timedelta
from decimal import Decimal

from sqlmodel import Session

from stockviz.schemas import (
    HoldoutResultOut,
    MonteCarloFanOut,
    RegimeRowOut,
    RegimeSplitOut,
    ReportCardOut,
    ReportMetricOut,
    SharpeStatsOut,
)
from stockviz.services.backtest import report
from stockviz.services.backtest.engine import DEFAULT_RISK_FREE_RATE
from stockviz.services.backtest.regime_history import METHOD, regime_history, states_on

PSR_FORMULA = (
    "PSR(SR*) = Phi((SR - SR*) sqrt(T - 1) / sqrt(1 - skew x SR + (kurt - 1)/4 x SR^2)), "
    "SR per day, SR* = 0 (Bailey and Lopez de Prado, 2012)"
)


def template_trips(
    trades: Sequence[tuple[date, str, Decimal, Decimal, Decimal]],
    last: tuple[date, Decimal] | None,
) -> list[report.Trip]:
    """Round trips from a template's legs ``(date, side, price, shares, fees)``;
    a position still held is marked at the last close (open)."""
    trips: list[report.Trip] = []
    entry: tuple[date, Decimal, Decimal] | None = None
    for day, side, price, shares, fees in trades:
        if side == "buy":
            entry = (day, shares, price * shares + fees)
        elif entry is not None:
            trips.append(report.Trip(entry[0], day, price * shares - fees - entry[2], None, False))
            entry = None
    if entry is not None and last is not None:
        trips.append(report.Trip(entry[0], last[0], entry[1] * last[1] - entry[2], None, True))
    return trips


def sharpe_out(stats: report.SharpeStats) -> SharpeStatsOut:
    return SharpeStatsOut(
        observations=stats.observations,
        sharpe=stats.sharpe,
        sharpe_annual=stats.sharpe_annual,
        skewness=stats.skewness,
        kurtosis=stats.kurtosis,
        risk_free_rate=DEFAULT_RISK_FREE_RATE,
        psr=stats.psr,
        formula=PSR_FORMULA,
    )


def build(
    session: Session,
    *,
    ticker: str,
    curve: Sequence[tuple[date, Decimal]],
    trips: Sequence[report.Trip],
    initial_cash: Decimal,
    max_drawdown: float,
    periods_per_year: float = report.TRADING_DAYS_PER_YEAR,
    session_days: Sequence[date] | None = None,
) -> tuple[ReportCardOut, report.SharpeStats]:
    """A6.4: an intraday run passes its bars a year and each curve point's
    session date: the fan is labelled by it, and a bar reads the regime of
    the day before its session (a regime state is known at the close)."""
    navs = [n for _, n in curve]
    returns = report.nav_returns(navs)
    stats = report.sharpe_stats(returns, periods_per_year)
    dates = [d for d, _ in curve]
    fan_dates = list(session_days) if session_days is not None else dates
    fan = report.mc_fan(returns, fan_dates, float(initial_cash)) if curve else None
    mc = (
        MonteCarloFanOut.model_validate({**fan, "actual_max_drawdown": max_drawdown})
        if fan is not None
        else None
    )
    if curve:
        days = [d - timedelta(days=1) for d in session_days] if session_days is not None else dates
        history = regime_history(session, ticker, days[0], days[-1])
        rows = report.regime_split(curve, states_on(history, days), trips, periods_per_year)
        regimes = RegimeSplitOut(
            market=history.market,
            index=history.index,
            rows=[
                RegimeRowOut(
                    state=r["state"],
                    sessions=r["sessions"],
                    share=r["share"],
                    total_return=r["return"],
                    sharpe=r["sharpe"],
                    exposure=r["exposure"],
                    trades_entered=r["trades_entered"],
                )
                for r in rows
            ],
            index_sessions=history.index_sessions,
            breadth_sessions=history.breadth_sessions,
            method=METHOD,
            reason=history.reason,
        )
    else:
        regimes = RegimeSplitOut(method=METHOD, reason="No sessions in the range.")
    card = ReportCardOut(
        metrics=[
            ReportMetricOut.model_validate(m)
            for m in report.metrics(curve, trips, initial_cash, max_drawdown, periods_per_year)
        ],
        sharpe=sharpe_out(stats),
        monte_carlo=mc,
        monte_carlo_reason=(
            None
            if mc is not None
            else f"Needs at least {report.MC_MIN_RETURNS} daily returns to resample."
        ),
        regimes=regimes,
    )
    return card, stats


def holdout_result(
    *,
    start: date,
    end: date,
    total_return: float,
    sharpe: float,
    max_drawdown: float,
    navs: Sequence[Decimal],
    trades: int,
) -> HoldoutResultOut:
    stats = report.sharpe_stats(report.nav_returns(navs))
    return HoldoutResultOut(
        from_date=start,
        to_date=end,
        total_return=total_return,
        sharpe=sharpe,
        max_drawdown=max_drawdown,
        psr=stats.psr,
        trades=trades,
    )


__all__ = ["build", "holdout_result", "sharpe_out", "template_trips"]
