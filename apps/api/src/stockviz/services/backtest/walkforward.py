"""Walk-forward tests and capped parameter sweeps (Phase 5.5).

Walk-forward (owner decision 4: 3-year in-sample, 1-year out-of-sample,
yearly steps, at most 50 settings):

1. Split ``[from, to]`` into rolling windows: in-sample ``[t, t + IS)``,
   out-of-sample ``[t + IS, t + IS + OOS)``, then ``t += step``.
2. On each in-sample period, run every setting in the grid and pick the best
   by the score (Sharpe, or total return).
3. Run that setting on the following out-of-sample period, starting with the
   capital the previous window ended with.
4. The stitched out-of-sample equity curve is the result. In-sample scores
   are kept only as context: they are what the setting was fitted to.

A sweep runs every setting over the whole range and ranks them; the result
says how many were tried, so "the best" is visibly one of N.

Bars are loaded once and every run is in memory (the kernel does about
140,000 fills a second), so a 50-setting walk-forward over ten years runs in
a request. Each run uses the same engine, kernel profile, costs and fees as
``POST /v1/backtest``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

from sqlmodel import Session

from stockviz.models import PriceBar, Symbol
from stockviz.schemas import BacktestIn
from stockviz.services.backtest.engine import (
    BacktestError,
    BacktestResult,
    _max_drawdown,
    _sharpe,
    run_backtest,
    warmup_bars_for,
)
from stockviz.services.backtest.run import (
    BadRange,
    UnknownSymbol,
    check_fee_currency,
    fingerprint,
    load_bars,
    load_dividends,
    price_basis_of,
    strategy_of,
)

MAX_SETTINGS = 50
SCORES = ("sharpe", "total_return")


def default_grid(strategy_type: str) -> list[dict[str, Any]]:
    """Settings around the usual values when no grid is given: 15 for SMA (short < long), 16 for RSI."""
    if strategy_type == "sma_crossover":
        return [
            {"type": "sma_crossover", "short_window": s, "long_window": long_}
            for s in (5, 10, 20, 50)
            for long_ in (50, 100, 150, 200)
            if s < long_
        ]
    return [
        {"type": "rsi_threshold", "buy_below": b, "sell_above": a}
        for b in (20, 25, 30, 35)
        for a in (65, 70, 75, 80)
    ]


def _add_years(day: date, years: int) -> date:
    try:
        return day.replace(year=day.year + years)
    except ValueError:  # 29 Feb
        return day.replace(year=day.year + years, day=28)


def windows(start: date, end: date, is_years: int, oos_years: int, step_years: int):
    """(in-sample from, in-sample to, out-of-sample from, out-of-sample to), inclusive."""
    out = []
    t = start
    while True:
        oos_from = _add_years(t, is_years)
        if oos_from > end:
            break
        oos_to = min(end, date.fromordinal(_add_years(oos_from, oos_years).toordinal() - 1))
        out.append((t, date.fromordinal(oos_from.toordinal() - 1), oos_from, oos_to))
        t = _add_years(t, step_years)
    return out


@dataclass
class _Data:
    bars: list[PriceBar]
    dividends: dict
    currency: str


def _load(session: Session, body: BacktestIn, grid: list[BacktestIn]) -> _Data:
    ticker = body.ticker.upper()
    symbol = session.get(Symbol, ticker)
    if symbol is None:
        raise UnknownSymbol(f"Symbol {ticker!r} not found")
    if body.from_ > body.to:
        raise BadRange("'from' must be on or before 'to'")
    check_fee_currency(body.fee_schedule, symbol.currency or "USD")
    warm = max(warmup_bars_for(*strategy_of(g)) for g in grid)
    rows, before = load_bars(
        session,
        ticker,
        datetime.combine(body.from_, time.min),
        datetime.combine(body.to, time.max),
        warm,
    )
    divs = (
        load_dividends(session, ticker, body.from_, body.to) if body.return_mode == "total" else {}
    )
    return _Data(bars=before + rows, dividends=divs, currency=symbol.currency or "USD")


def _run(data: _Data, spec: BacktestIn, start: date, end: date, cash: Decimal) -> BacktestResult:
    """One run over [start, end] on the loaded bars, with its warm-up before start."""
    strategy_type, params = strategy_of(spec)
    begin = datetime.combine(start, time.min)
    finish = datetime.combine(end, time.max)
    inside = [b for b in data.bars if begin <= b.ts <= finish]
    warm = [b for b in data.bars if b.ts < begin][-warmup_bars_for(strategy_type, params) :]
    used = warm + inside
    divs = {d: a for d, a in data.dividends.items() if start <= d <= end} or None
    return run_backtest(
        [(b.ts, b.close) for b in used],
        initial_cash=cash,
        strategy_type=strategy_type,
        params=params,
        commission_bps=spec.commission_bps,
        slippage_bps=spec.slippage_bps,
        trade_from=begin,
        dividends=divs,
        opens={b.ts: b.open for b in used},
        fill_rule=spec.fill_rule,
        spread_bps=spec.spread_bps,
        fee_schedule=spec.fee_schedule,
    )


def _score(result: BacktestResult, score: str) -> float:
    return result.summary.sharpe if score == "sharpe" else result.summary.total_return


def _with(body: BacktestIn, strategy: dict[str, Any]) -> BacktestIn:
    return BacktestIn.model_validate(
        {**body.model_dump(mode="json", by_alias=True), "strategy": strategy}
    )


def _grid(body: BacktestIn, grid: list[dict[str, Any]] | None) -> list[BacktestIn]:
    settings = grid or default_grid(strategy_of(body)[0])
    if not 1 <= len(settings) <= MAX_SETTINGS:
        raise BacktestError(f"A grid needs 1 to {MAX_SETTINGS} settings")
    return [_with(body, s) for s in settings]


def _summary(navs: list[Decimal], start_cash: Decimal, bench: float, costs: Decimal) -> dict:
    final = navs[-1] if navs else start_cash
    total = float((final - start_cash) / start_cash)
    return {
        "total_return": total,
        "sharpe": _sharpe(navs),
        "max_drawdown": _max_drawdown(navs),
        "final_nav": str(final),
        "benchmark_return": bench,
        "benchmark_final_nav": str(start_cash * Decimal(str(1 + bench))),
        "excess_return": (total - bench) * 100,
        "total_costs": str(costs),
    }


@dataclass
class Computed:
    result: dict[str, Any]
    fingerprint: str
    bar_count: int
    first_bar_at: datetime | None
    last_bar_at: datetime | None


def walk_forward(
    session: Session,
    body: BacktestIn,
    *,
    grid: list[dict[str, Any]] | None = None,
    in_sample_years: int = 3,
    out_of_sample_years: int = 1,
    step_years: int = 1,
    score: str = "sharpe",
) -> Computed:
    if score not in SCORES:
        raise BacktestError(f"score must be one of {SCORES}")
    if min(in_sample_years, out_of_sample_years, step_years) < 1:
        raise BacktestError("in-sample, out-of-sample and step must be at least a year")
    specs = _grid(body, grid)
    plan = windows(body.from_, body.to, in_sample_years, out_of_sample_years, step_years)
    if not plan:
        raise BadRange(
            f"The range is shorter than one in-sample period ({in_sample_years} years) "
            "plus an out-of-sample day"
        )
    data = _load(session, body, specs)

    capital = body.initial_cash
    stitched: list[dict[str, Any]] = []
    navs: list[Decimal] = []
    costs = Decimal(0)
    out_windows = []
    for is_from, is_to, oos_from, oos_to in plan:
        fitted = [(spec, _run(data, spec, is_from, is_to, body.initial_cash)) for spec in specs]
        best_spec, best = max(fitted, key=lambda pair: _score(pair[1], score))
        oos = _run(data, best_spec, oos_from, oos_to, capital)
        for point in oos.equity_curve:
            stitched.append({"date": point.date.isoformat(), "nav": str(point.nav)})
            navs.append(point.nav)
        costs += oos.summary.total_costs
        out_windows.append(
            {
                "in_sample_from": is_from.isoformat(),
                "in_sample_to": is_to.isoformat(),
                "out_of_sample_from": oos_from.isoformat(),
                "out_of_sample_to": oos_to.isoformat(),
                "chosen": best_spec.strategy.model_dump(mode="json"),
                "in_sample_score": _score(best, score),
                "out_of_sample_return": oos.summary.total_return,
                "trades": len(oos.trades),
            }
        )
        if oos.equity_curve:
            capital = oos.equity_curve[-1].nav

    oos_start = datetime.combine(plan[0][2], time.min)
    oos_bars = [b for b in data.bars if b.ts >= oos_start]
    bench = (
        float(oos_bars[-1].close / oos_bars[0].close) - 1.0
        if len(oos_bars) > 1 and oos_bars[0].close
        else 0.0
    )
    result = {
        "result_kind": "walk_forward",
        "ticker": body.ticker.upper(),
        "currency": data.currency,
        "price_basis": price_basis_of(data.bars),
        "score": score,
        "in_sample_years": in_sample_years,
        "out_of_sample_years": out_of_sample_years,
        "step_years": step_years,
        "tried": len(specs),
        "windows": out_windows,
        "equity_curve": stitched,
        "summary": _summary(navs, body.initial_cash, bench, costs),
    }
    return _computed(result, data)


def sweep(
    session: Session,
    body: BacktestIn,
    *,
    grid: list[dict[str, Any]] | None = None,
    score: str = "sharpe",
) -> Computed:
    if score not in SCORES:
        raise BacktestError(f"score must be one of {SCORES}")
    specs = _grid(body, grid)
    data = _load(session, body, specs)
    runs = []
    for spec in specs:
        res = _run(data, spec, body.from_, body.to, body.initial_cash)
        navs = [p.nav for p in res.equity_curve]
        runs.append(
            {
                "strategy": spec.strategy.model_dump(mode="json"),
                "score": _score(res, score),
                "summary": _summary(
                    navs,
                    body.initial_cash,
                    res.summary.benchmark_return,
                    res.summary.total_costs,
                ),
                "trades": len(res.trades),
            }
        )
    runs.sort(key=lambda r: r["score"], reverse=True)
    result = {
        "result_kind": "sweep",
        "ticker": body.ticker.upper(),
        "currency": data.currency,
        "price_basis": price_basis_of(data.bars),
        "score": score,
        "tried": len(runs),
        "runs": runs,
        "summary": runs[0]["summary"],
    }
    return _computed(result, data)


def _computed(result: dict[str, Any], data: _Data) -> Computed:
    return Computed(
        result=result,
        fingerprint=fingerprint(data.bars, data.dividends),
        bar_count=len(data.bars),
        first_bar_at=data.bars[0].ts if data.bars else None,
        last_bar_at=data.bars[-1].ts if data.bars else None,
    )
