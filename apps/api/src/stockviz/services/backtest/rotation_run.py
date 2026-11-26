"""Load a rotation's data and run it (A4.4).

``execute_rotation`` resolves the universe (your watchlist or a list of up
to 50, one currency), compiles the ranking (a numeric Rule DSL expression)
and the optional cash filter, loads each symbol through ``dsl.load_symbol``
(the ranking's values) and ``price_bars`` (the ``Decimal`` prices fills
use), works out the rebalance sessions on the venue calendar, judges the cash
filter on the market index, and hands everything to the pure
:func:`rotation.run_rotation`. The public ``POST /v1/backtest/rotation`` and
the experiment registry both call it.

The **cash filter** is judged on the market index's own daily bars (``^GSPC``
for US listings, ``^NSEI`` for Indian ones), where ``index_close`` is the
index's close, so ``index_close < sma(index_close, 200)`` reads the market.
It may read prices only (no fundamentals, news, delivery or drawings). Its
value on a rebalance session is the index's on the newest index bar on or
before it, at most 5 sessions back; otherwise it is unknown and does not act.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pandas as pd
from sqlmodel import Session

from stockviz.models import Symbol
from stockviz.schemas import (
    EquityPointOut,
    RotationBacktestIn,
    RotationBacktestOut,
    RotationRankOut,
    RotationRebalanceOut,
    RotationRuleOut,
    RotationTradeOut,
    RotationTurnoverOut,
    RotationUnrankedOut,
    StrategyBenchmarkOut,
    StrategySummaryOut,
)
from stockviz.services.backtest import report_card
from stockviz.services.backtest.engine import FILL_RULES, BacktestError
from stockviz.services.backtest.report import SharpeStats, Trip
from stockviz.services.backtest.rotation import (
    VOL_WINDOW,
    RotationError,
    RotationSymbol,
    rebalance_signals,
    run_rotation,
)
from stockviz.services.backtest.run import check_fee_currency
from stockviz.services.backtest.strategy import StrategyError
from stockviz.services.backtest.strategy_run import (
    StrategyNeedsUser,
    StrategyNotFound,
    _float_list,
    _price_rows,
    _resolve_rule,
    _universe,
)
from stockviz.services.backtest.trials import split_window
from stockviz.services.backtest.universe import universe_for
from stockviz.services.bars.resample import bar_date
from stockviz.services.dsl import Needs, load_symbol, vector
from stockviz.services.event_study import benchmark_for
from stockviz.services.fee_view import costs_out, is_indian, liquidity_out, resolve_fee_schedule
from stockviz.services.instruments import is_index_ticker
from stockviz.services.markets.calendar import venue_for_ticker
from stockviz.services.setups.rules import compile_number
from stockviz.services.simulation import CostModel, get_fee_schedule
from stockviz.services.trading.simulation_adapter import as_aware_utc

FILTER_FFILL_SESSIONS = 5
TURNOVER_DEFINITION = (
    "One-way turnover per rebalance = (value bought + value sold) / 2 / equity at the "
    "rebalance close; annualised = the sum over the run / its length in years."
)
TIMING = (
    "Ranks on the last session of each {period} on the {venue} calendar, from values known "
    "at that session's close (vector mode, no later bar); orders fill on each symbol's next "
    "bar ({profile}). The first ranking is on the last session before the window, so the run "
    "is invested from its first session; a {period} still running at the end does not rebalance."
)


@dataclass(frozen=True)
class RotationRun:
    out: RotationBacktestOut
    fingerprint: str
    bar_count: int
    first_bar_at: datetime | None
    last_bar_at: datetime | None
    stats: SharpeStats | None = None

    @property
    def label(self) -> str:
        tickers = self.out.tickers
        return tickers[0] if len(tickers) == 1 else f"{tickers[0]}+{len(tickers) - 1}"[:16]


def rotation_hash(body: RotationBacktestIn, rules: dict[str, str], tickers: list[str]) -> str:
    payload = {
        "mode": "rotation",
        "rules": rules,
        "top_n": body.top_n,
        "schedule": body.schedule,
        "weighting": body.weighting,
        "buffer": body.buffer,
        "tickers": tickers,
        "from": body.from_.isoformat(),
        "to": body.to.isoformat(),
        "initial_cash": str(body.initial_cash),
        "fill_rule": body.fill_rule,
        "fee_schedule": body.fee_schedule,
        "brokerage": body.brokerage,
        "adv_cap_pct": body.adv_cap_pct,
        "commission_bps": body.commission_bps,
        "slippage_bps": body.slippage_bps,
        "spread_bps": body.spread_bps,
        "holdout": body.holdout,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def _volatility(closes: Any) -> list[float | None]:
    returns = closes.pct_change()
    sd = returns.rolling(VOL_WINDOW, min_periods=VOL_WINDOW).std(ddof=1)
    return [None if pd.isna(v) else float(v) for v in sd.tolist()]


FACTOR_MIN_SYMBOLS = 3


def factor_scores(
    inputs: list[RotationSymbol],
    values: dict[str, list[list[float | None]]],
    factors: list[Any],
) -> list[RotationSymbol]:
    """A7.7 (M7.5): each symbol's score on each date is the weighted sum of its
    factors' cross-sectional z-scores that date (sign flipped where lower is
    better). A date counts the symbols with every factor known; under
    ``FACTOR_MIN_SYMBOLS`` of them, or a factor with no spread, nobody is
    scored that date (unknown, so never ranked). Pure; values only from bars up
    to each date, so no look-ahead."""
    by_date: dict[date, dict[str, list[float]]] = {}
    for sym in inputs:
        rows = values.get(sym.ticker, [])
        for i, day in enumerate(sym.dates):
            point = [col[i] for col in rows]
            if point and all(v is not None and math.isfinite(v) for v in point):
                by_date.setdefault(day, {})[sym.ticker] = [float(v) for v in point]  # type: ignore[arg-type]
    composite: dict[tuple[str, date], float] = {}
    for day, members in by_date.items():
        if len(members) < FACTOR_MIN_SYMBOLS:
            continue
        columns = list(zip(*members.values(), strict=True))
        stats = []
        for col in columns:
            mean = sum(col) / len(col)
            sd = math.sqrt(sum((v - mean) ** 2 for v in col) / (len(col) - 1))
            stats.append((mean, sd))
        if any(sd == 0 for _m, sd in stats):
            continue
        for ticker, point in members.items():
            total = 0.0
            for f, v, (mean, sd) in zip(factors, point, stats, strict=True):
                z = (v - mean) / sd
                total += f.weight * (z if f.higher_is_better else -z)
            composite[(ticker, day)] = total
    return [
        replace(sym, score=[composite.get((sym.ticker, d)) for d in sym.dates]) for sym in inputs
    ]


def execute_rotation(
    session: Session, body: RotationBacktestIn, *, user_id: int | None
) -> RotationRun:
    """Raises ``StrategyNotFound``, ``StrategyNeedsUser``, ``StrategyError``
    or ``RuleError``."""
    if body.from_ > body.to:
        raise StrategyError("'from' must be on or before 'to'")
    window = split_window(body.from_, body.to, body.holdout)
    # A7.7: a factor model compiles each factor; their sum supplies the
    # combined warm-up and inputs to load (its values are never used).
    factor_rules = [compile_number(f.expression) for f in body.factors] if body.factors else []
    if factor_rules:
        assert body.factors is not None
        ranking = compile_number(" + ".join(f"({f.expression})" for f in body.factors))
    else:
        assert body.ranking is not None
        ranking = compile_number(body.ranking)  # RuleError: the router's 422
    if ranking.user_scoped and user_id is None:
        raise StrategyNeedsUser("This ranking reads your drawings: sign in to run it")
    cash_rule = (
        _resolve_rule(session, body.cash_filter, "cash_filter", user_id)
        if body.cash_filter is not None
        else None
    )
    if cash_rule is not None:
        n = cash_rule.compiled.needs
        if n.fundamentals or n.news or n.delivery or n.drawings:
            raise StrategyError(
                "The cash filter is judged on the market index: it can read prices and "
                "index_close only (no fundamentals, news, delivery or drawings)"
            )
    tickers, source = _universe(session, body, user_id)
    if len(tickers) < 2:
        raise StrategyError("A rotation needs at least two symbols")
    if body.top_n > len(tickers):
        raise StrategyError(f"top_n ({body.top_n}) is more than the {len(tickers)} symbols")

    currencies: dict[str, str] = {}
    for ticker in tickers:
        symbol = session.get(Symbol, ticker)
        if symbol is None:
            raise StrategyNotFound(f"Symbol {ticker!r} not found")
        if is_index_ticker(ticker):
            raise StrategyError(f"{ticker} is an index: it cannot be traded")
        currencies[ticker] = symbol.currency or "USD"
    if len(set(currencies.values())) > 1:
        listed = ", ".join(f"{t} {c}" for t, c in currencies.items())
        raise StrategyError(
            f"A rotation must trade in one currency (got {listed}); split it by market"
        )
    currency = currencies[tickers[0]]
    defaults = {resolve_fee_schedule(body.fee_schedule, t) for t in tickers}
    if len(defaults) > 1:
        raise StrategyError(
            "The universe spans markets with different default fee schedules "
            f"({', '.join(sorted(defaults))}); choose one fee schedule"
        )
    schedule_name = defaults.pop()
    try:
        check_fee_currency(schedule_name, currency)
    except BacktestError as exc:
        raise StrategyError(str(exc)) from exc
    venue = venue_for_ticker(tickers[0])
    index_ticker = benchmark_for(tickers[0])
    if cash_rule is not None and index_ticker is None:
        raise StrategyError(f"No market index for {tickers[0]}'s market: drop the cash filter")

    vol_needed = body.weighting == "inverse_volatility"
    lookback = ranking.lookback
    if lookback is not None:
        lookback = max(lookback, VOL_WINDOW + 1 if vol_needed else 0) + 1
    needs = ranking.needs
    digest = hashlib.sha256()
    if factor_rules:
        assert body.factors is not None
        for f, rule in zip(body.factors, factor_rules, strict=True):
            digest.update(f"factor|{rule.hash}|{f.weight}|{f.higher_is_better}\n".encode())
    else:
        digest.update(f"ranking|{ranking.hash}\n".encode())
    factor_values: dict[str, list[list[float | None]]] = {}
    inputs: list[RotationSymbol] = []
    bases: set[str] = set()
    bar_count = 0
    first_at: datetime | None = None
    last_at: datetime | None = None
    for ticker in tickers:
        data = load_symbol(
            session, ticker, end=window.to_date, start=window.from_date, lookback=lookback,
            needs=needs, user_id=user_id,
        )  # fmt: skip
        dates = data.dates
        if not dates:
            continue
        tv = venue_for_ticker(ticker)
        rows = [r for r in _price_rows(session, ticker, dates[0], window.to_date)
                if bar_date(r.ts, tv) >= dates[0]]  # fmt: skip
        if [bar_date(r.ts, tv) for r in rows] != dates:
            raise StrategyError(f"{ticker}: the bars changed while loading; run it again")
        first = next((i for i, d in enumerate(dates) if d >= window.from_date), len(dates))
        if first >= len(dates):
            continue
        inputs.append(
            RotationSymbol(
                ticker=ticker,
                dates=dates,
                ts=[as_aware_utc(r.ts) for r in rows],
                open=[r.open for r in rows],
                high=[r.high for r in rows],
                low=[r.low for r in rows],
                close=[r.close for r in rows],
                volume=[Decimal(r.volume) for r in rows],
                score=([None] * len(dates) if factor_rules else _float_list(vector(ranking, data))),
                first=first,
                vol=_volatility(data.bars["close"]) if vol_needed else None,
            )
        )
        if factor_rules:
            factor_values[ticker] = [_float_list(vector(rule, data)) for rule in factor_rules]
        digest.update(f"symbol|{ticker}\n".encode())
        for r in rows:
            digest.update(
                f"{r.ts.isoformat()}|{r.open}|{r.high}|{r.low}|{r.close}|{r.volume}|"
                f"{r.adjustment_semantics}\n".encode()
            )
            bases.add(str(r.adjustment_semantics))
        if data.benchmark is not None:
            days = pd.DatetimeIndex(data.benchmark.index).strftime("%Y-%m-%d").tolist()
            digest.update(
                f"bench|{list(zip(days, data.benchmark.tolist(), strict=True))!r}\n".encode()
            )
        for part in ("fundamentals", "news", "drawings"):
            value = getattr(data, part)
            if value is not None:
                digest.update(f"{part}|{value!r}\n".encode())
        if needs.delivery:
            for name in ("delivery_pct", "deliverable_qty"):
                digest.update(f"{name}|{data.bars[name].tolist()!r}\n".encode())
        bar_count += len(rows)
        first_at = rows[0].ts if first_at is None else min(first_at, rows[0].ts)
        last_at = rows[-1].ts if last_at is None else max(last_at, rows[-1].ts)

    if factor_rules:
        assert body.factors is not None
        inputs = factor_scores(inputs, factor_values, body.factors)

    signals = rebalance_signals(window.from_date, window.to_date, body.schedule, venue)

    filter_values: dict[date, bool | None] | None = None
    if cash_rule is not None:
        assert index_ticker is not None
        lb = cash_rule.compiled.lookback
        idx = load_symbol(
            session, index_ticker, end=window.to_date, start=window.from_date,
            lookback=None if lb is None else lb + 10, needs=Needs(),
        )  # fmt: skip
        idx = replace(idx, benchmark=idx.bars["close"], benchmark_ticker=index_ticker)
        values = vector(cash_rule.compiled, idx)
        idx_dates = idx.dates
        digest.update(f"cash_filter|{cash_rule.compiled.hash}|{index_ticker}\n".encode())
        digest.update(
            f"{list(zip(idx_dates, idx.bars['close'].tolist(), strict=True))!r}\n".encode()
        )
        flags = [None if pd.isna(v) else bool(v) for v in values.tolist()]
        filter_values = {}
        for d in signals:
            pos = _asof(idx_dates, d)
            if pos is None or _sessions_between(idx_dates, pos, d) > FILTER_FFILL_SESSIONS:
                filter_values[d] = None
            else:
                filter_values[d] = flags[pos]

    profile = FILL_RULES[body.fill_rule]
    costs = CostModel(
        spread_bps=Decimal(str(body.spread_bps)), slippage_bps=Decimal(str(body.slippage_bps))
    )
    try:
        result = run_rotation(
            inputs, signals=signals, cash_filter=filter_values, top_n=body.top_n,
            buffer=body.buffer, weighting=body.weighting, initial_cash=body.initial_cash,
            profile=profile, costs=costs, schedule=get_fee_schedule(schedule_name),
            commission_bps=Decimal(str(body.commission_bps)), brokerage=body.brokerage,
            adv_cap_pct=body.adv_cap_pct,
        ) if inputs else None  # fmt: skip
    except RotationError as exc:
        raise StrategyError(str(exc)) from exc

    if factor_rules:
        assert body.factors is not None
        combined = " + ".join(
            f"{f.weight:g} x {'' if f.higher_is_better else '-'}z({rule.canonical_text})"
            for f, rule in zip(body.factors, factor_rules, strict=True)
        )
        rules_out = [
            RotationRuleOut(
                role="ranking",
                text=f"Factor model: {combined}",
                canonical=combined,
                hash=hashlib.sha256(combined.encode()).hexdigest(),
                warmup_bars=ranking.lookback,
            ),
            *[
                RotationRuleOut(
                    role="factor",
                    text=f"{f.name or 'factor'}: {rule.text}",
                    canonical=rule.canonical_text,
                    hash=rule.hash,
                    warmup_bars=rule.lookback,
                )
                for f, rule in zip(body.factors, factor_rules, strict=True)
            ],
        ]
    else:
        rules_out = [
            RotationRuleOut(
                role="ranking",
                text=ranking.text,
                canonical=ranking.canonical_text,
                hash=ranking.hash,
                warmup_bars=ranking.lookback,
            )
        ]
    if cash_rule is not None:
        rules_out.append(
            RotationRuleOut(
                role="cash_filter",
                text=cash_rule.compiled.text,
                canonical=cash_rule.compiled.canonical_text,
                hash=cash_rule.compiled.hash,
                setup_version_id=cash_rule.version_id,
                warmup_bars=cash_rule.compiled.lookback,
            )
        )
    period = "week" if body.schedule == "weekly" else "month"
    timing = TIMING.format(period=period, venue=venue,
                           profile=f"{profile.name}/{profile.model_version}")  # fmt: skip
    notes = [
        "Each rebalance resizes to the targets: names leaving are sold in full, names that "
        "stay are trimmed or topped up to their weight, names entering are bought to theirs "
        "(whole shares, capped by free cash; sells fill before buys).",
        "Unknown ranking values are never ranked; ties go to the ticker that sorts first.",
        "Price return: dividends are not credited. Whole shares only. Holdings at the end "
        "are marked at the last close, not sold.",
    ]
    if cash_rule is not None:
        notes.append(
            f"The cash filter is judged on {index_ticker}'s own bars at each rebalance close; "
            "met: sell everything and hold cash; unknown: it does not act."
        )
    loaded = {i.ticker for i in inputs}
    missing = [t for t in tickers if t not in loaded]
    if missing:
        notes.append(f"No bars in the range for: {', '.join(missing)}.")

    cash = body.initial_cash
    if result is None:
        trades: list[RotationTradeOut] = []
        curve: list[EquityPointOut] = []
        rebalances: list[RotationRebalanceOut] = []
        summary = StrategySummaryOut(total_return=0.0, sharpe=0.0, max_drawdown=0.0,
                                     final_nav=cash, benchmark_final_nav=cash,
                                     gross_final_nav=cash)  # fmt: skip
        bench_return, bench_final = 0.0, cash
        skip_reasons: dict[str, int] = {}
        filter_unknown = unfilled = 0
    else:
        trades = [
            RotationTradeOut(
                ticker=t.ticker,
                entry_date=t.entry_date,
                entry_price=t.entry_price,
                entry_reference_price=t.entry_reference,
                exit_date=t.exit_date,
                exit_price=t.exit_price,
                exit_reference_price=t.exit_reference,
                quantity=t.quantity,
                entry_fees=t.entry_fees,
                exit_fees=t.exit_fees,
                pnl=t.pnl,
                return_pct=t.return_pct,
                reason=t.reason,
                open=t.open,
                bars_held=t.bars_held,
                requested_quantity=t.requested_quantity,
                exit_adv_pct=t.exit_adv_pct,
            )
            for t in result.trades
        ]
        curve = [EquityPointOut(date=d, nav=nav) for d, nav in result.equity_curve]
        rebalances = [
            RotationRebalanceOut(
                signal_date=r.signal_date,
                trade_dates=sorted(r.trade_dates),
                equity=r.equity,
                cash_filter=r.cash_filter,
                skipped=r.skipped,
                ranked=[
                    RotationRankOut(ticker=e.ticker, value=_round(e.value), rank=e.rank)
                    for e in r.ranked
                ],
                unranked=[
                    RotationUnrankedOut(ticker=u.ticker, reason=u.reason) for u in r.unranked
                ],
                held_before=r.before,
                held_after=r.target,
                entered=r.entered,
                exited=r.exited,
                weights={k: round(v, 6) for k, v in r.weights.items()},
                bought=r.bought.quantize(Decimal("0.01")),
                sold=r.sold.quantize(Decimal("0.01")),
                turnover=round(r.turnover, 6),
                replaced_orders=r.replaced,
                not_filled=r.not_filled,
            )
            for r in result.rebalances
        ]
        gross = result.gross_final_nav
        summary = StrategySummaryOut(
            total_return=result.total_return,
            sharpe=result.sharpe,
            max_drawdown=result.max_drawdown,
            final_nav=result.final_nav,
            benchmark_return=result.benchmark_return,
            benchmark_final_nav=result.benchmark_final_nav,
            excess_return=(result.total_return - result.benchmark_return) * 100,
            total_costs=result.total_costs,
            gross_return=float((gross - cash) / cash),
            gross_final_nav=gross,
            total_fees=result.total_fees,
            price_costs=result.price_costs,
            trade_count=len(result.trades),
        )
        bench_return, bench_final = result.benchmark_return, result.benchmark_final_nav
        skip_reasons = result.skip_reasons
        filter_unknown = result.cash_filter_unknown
        unfilled = result.unfilled_at_end

    traded = [r for r in rebalances if r.skipped is None]
    total_turnover = sum(r.turnover for r in traded)
    years = max((window.to_date - window.from_date).days / 365.25, 1 / 365.25)
    turnover = RotationTurnoverOut(
        rebalances=len(traded),
        mean_per_rebalance=round(total_turnover / len(traded), 6) if traded else 0.0,
        total=round(total_turnover, 6),
        annualised=round(total_turnover / years, 6),
        definition=TURNOVER_DEFINITION,
    )
    if skip_reasons:
        words = {"no_cash": "not enough cash for one share",
                 "adv_cap": "the ADV cap allowed no whole share"}  # fmt: skip
        notes.append(
            "Buys not filled: "
            + ", ".join(f"{n} ({words.get(k, k)})" for k, n in skip_reasons.items())
            + "."
        )

    card, stats = report_card.build(
        session,
        ticker=tickers[0],
        curve=[(p.date, p.nav) for p in curve],
        trips=[Trip(t.entry_date, t.exit_date, t.pnl, None, t.open) for t in trades],
        initial_cash=cash,
        max_drawdown=summary.max_drawdown,
    )
    rule_hashes = {r.role: r.hash for r in rules_out}
    out = RotationBacktestOut(
        tickers=tickers,
        currency=currency,
        price_basis=None if not bases else bases.pop() if len(bases) == 1 else "mixed",
        execution_profile=f"{profile.name}/{profile.model_version}",
        fee_schedule=schedule_name if body.fee_schedule == "auto" else body.fee_schedule,
        rules=rules_out,
        top_n=body.top_n,
        schedule=body.schedule,
        weighting=body.weighting,
        buffer=body.buffer,
        venue=venue,
        cash_filter_index=index_ticker if cash_rule is not None else None,
        timing=timing,
        rebalances=rebalances,
        trades=trades,
        equity_curve=curve,
        summary=summary,
        benchmark=StrategyBenchmarkOut(
            kind="equal_weight_buy_and_hold",
            tickers=[i.ticker for i in inputs],
            total_return=bench_return,
            final_nav=bench_final,
        ),
        turnover=turnover,
        source=source,
        universe=universe_for(tickers[0]),
        warmup_bars=max((i.first for i in inputs), default=0),
        cash_filter_unknown=filter_unknown,
        unfilled_at_end=unfilled,
        skip_reasons=skip_reasons,
        strategy_hash=rotation_hash(body, rule_hashes, tickers),
        data_fingerprint=digest.hexdigest(),
        notes=notes,
        costs=costs_out(
            requested=body.fee_schedule,
            resolved=schedule_name,
            brokerage=body.brokerage,
            commission_bps=body.commission_bps,
            fee_versions=result.fee_versions if result is not None else {},
            fills_before_coverage=result.fills_before_coverage if result is not None else 0,
            indian=any(is_indian(t) for t in tickers),
        ),
        liquidity=liquidity_out(
            body.adv_cap_pct,
            partial=result.partial_entries if result is not None else 0,
            skipped=skip_reasons.get("adv_cap", 0),
            unknown=result.adv_unknown if result is not None else 0,
        ),
        window=window,
        report=card,
    )
    return RotationRun(
        out=out,
        fingerprint=out.data_fingerprint,
        bar_count=bar_count,
        first_bar_at=first_at,
        last_bar_at=last_at,
        stats=stats,
    )


def _round(value: float) -> float:
    return round(value, 6) if math.isfinite(value) else value


def _asof(dates: list[date], day: date) -> int | None:
    """Index of the newest date on or before ``day``."""
    lo, hi = 0, len(dates)
    while lo < hi:
        mid = (lo + hi) // 2
        if dates[mid] <= day:
            lo = mid + 1
        else:
            hi = mid
    return lo - 1 if lo > 0 else None


def _sessions_between(dates: list[date], pos: int, day: date) -> int:
    """Weekdays from ``dates[pos]`` to ``day`` (a stale index bar is unknown)."""
    start = dates[pos]
    n, probe = 0, start
    while probe < day:
        probe += timedelta(days=1)
        if probe.weekday() < 5:
            n += 1
    return n


def request_json(body: RotationBacktestIn) -> dict[str, Any]:
    return body.model_dump(mode="json", by_alias=True)


__all__ = ["RotationRun", "execute_rotation", "request_json", "rotation_hash"]
