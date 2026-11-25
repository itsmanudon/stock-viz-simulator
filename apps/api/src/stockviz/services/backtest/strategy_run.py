"""Load a Rule DSL strategy's data and run it (A4.1).

``execute_strategy`` resolves the rules (setup versions or inline text),
the universe (a ticker, the caller's watchlist, or a list), loads each
symbol through ``dsl.load_symbol`` (signals) and ``price_bars`` (the
``Decimal`` prices fills use), computes the vector-mode signals and ATR
series, and hands them to the pure :func:`strategy.run_strategy`. The public
``POST /v1/backtest/strategy`` and the experiment registry both call it.

The result carries a **strategy hash** (SHA-256 of the canonical strategy:
rule hashes, stops, sizing, universe, dates, costs) and a **data fingerprint**
(SHA-256 of every bar, benchmark close, fact, news document and drawing the
rules read, warm-up included), so a rerun can say identical, different or
data changed.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

import pandas as pd
from sqlmodel import Session, col, select

from stockviz.models import PriceBar, Symbol
from stockviz.models.setup import Setup
from stockviz.models.watchlist import Watchlist, WatchlistItem
from stockviz.schemas import (
    EquityPointOut,
    StrategyBacktestIn,
    StrategyBacktestOut,
    StrategyBenchmarkOut,
    StrategyRuleIn,
    StrategyRuleOut,
    StrategySummaryOut,
    StrategySymbolOut,
    StrategyTradeOut,
    StrategyUniverseSourceOut,
)
from stockviz.services.backtest.engine import FILL_RULES, BacktestError
from stockviz.services.backtest.run import check_fee_currency
from stockviz.services.backtest.strategy import (
    STOP_PRIORITY,
    Sizing,
    Stops,
    StrategyError,
    SymbolInput,
    run_strategy,
)
from stockviz.services.backtest.universe import universe_for
from stockviz.services.bars.resample import bar_date
from stockviz.services.dsl import CompiledRule, Needs, compile_rule, load_symbol, vector
from stockviz.services.instruments import instrument_of, is_index_ticker
from stockviz.services.markets.calendar import NEW_YORK_VENUE, venue_for_ticker
from stockviz.services.setups import store
from stockviz.services.simulation import CostModel, get_fee_schedule
from stockviz.services.trading.simulation_adapter import as_aware_utc

INLINE_SETUP_NAME = "Rules from backtests"
"""The setup that holds a user's inline backtest rules, one version each."""


class StrategyNotFound(LookupError):
    """An unknown symbol, setup version or watchlist (a 404)."""


class StrategyNeedsUser(PermissionError):
    """A watchlist or a rule that reads drawings needs a signed-in caller (a 401)."""


@dataclass(frozen=True)
class StrategyRun:
    out: StrategyBacktestOut
    fingerprint: str
    bar_count: int
    first_bar_at: datetime | None
    last_bar_at: datetime | None
    entry_version_id: int | None

    @property
    def label(self) -> str:
        tickers = self.out.tickers
        return tickers[0] if len(tickers) == 1 else f"{tickers[0]}+{len(tickers) - 1}"[:16]


@dataclass(frozen=True)
class _Rule:
    role: str
    compiled: CompiledRule
    version_id: int | None


def _resolve_rule(session: Session, ref: StrategyRuleIn, role: str, user_id: int | None) -> _Rule:
    if ref.setup_version_id is not None:
        try:
            version = store.visible_version(session, ref.setup_version_id, user_id)
        except store.SetupNotFound as exc:
            raise StrategyNotFound(f"Setup version {ref.setup_version_id} not found") from exc
        compiled = compile_rule(version.rule_text)
        rule = _Rule(role, compiled, version.id)
    else:
        assert ref.rule is not None
        rule = _Rule(role, compile_rule(ref.rule), None)  # RuleError: the router's 422
    if rule.compiled.user_scoped and user_id is None:
        raise StrategyNeedsUser("This rule reads your drawings: sign in to run it")
    return rule


def _universe(
    session: Session, body: StrategyBacktestIn, user_id: int | None
) -> tuple[list[str], StrategyUniverseSourceOut]:
    u = body.universe
    if u.ticker is not None:
        tickers = [u.ticker.strip().upper()]
        source = StrategyUniverseSourceOut(kind="ticker", tickers=tickers)
    elif u.watchlist_id is not None:
        if user_id is None:
            raise StrategyNeedsUser("Sign in to backtest a watchlist")
        wl = session.get(Watchlist, u.watchlist_id)
        if wl is None or wl.user_id != user_id:
            raise StrategyNotFound(f"Watchlist {u.watchlist_id} not found")
        rows = session.exec(
            select(WatchlistItem)
            .where(col(WatchlistItem.watchlist_id) == wl.id)
            .order_by(col(WatchlistItem.added_at), col(WatchlistItem.ticker))
        ).all()
        tickers = [r.ticker.upper() for r in rows][:50]
        if not tickers:
            raise StrategyError(f"Watchlist {wl.name!r} is empty")
        source = StrategyUniverseSourceOut(
            kind="watchlist", watchlist_id=wl.id, name=wl.name, tickers=tickers
        )
    else:
        assert u.tickers is not None
        tickers = list(dict.fromkeys(t.strip().upper() for t in u.tickers if t.strip()))
        if not tickers:
            raise StrategyError("The ticker list is empty")
        source = StrategyUniverseSourceOut(kind="list", tickers=tickers)
    return tickers, source


def _strategy_hash(body: StrategyBacktestIn, rules: list[_Rule], tickers: list[str]) -> str:
    payload = {
        "rules": {r.role: r.compiled.hash for r in rules},
        "stops": body.stops.model_dump(mode="json"),
        "sizing": body.sizing.model_dump(mode="json"),
        "tickers": tickers,
        "from": body.from_.isoformat(),
        "to": body.to.isoformat(),
        "initial_cash": str(body.initial_cash),
        "fill_rule": body.fill_rule,
        "fee_schedule": body.fee_schedule,
        "commission_bps": body.commission_bps,
        "slippage_bps": body.slippage_bps,
        "spread_bps": body.spread_bps,
        "direction": body.direction,
        "shortable": sorted({t.upper() for t in body.shortable}),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def _bool_list(series: pd.Series) -> list[bool | None]:
    return [None if pd.isna(v) else bool(v) for v in series.tolist()]


def _float_list(series: pd.Series) -> list[float | None]:
    return [None if pd.isna(v) else float(v) for v in series.tolist()]


def _price_rows(session: Session, ticker: str, first: date, end: date) -> list[PriceBar]:
    lower = datetime.combine(first - timedelta(days=1), time.min)
    upper = datetime.combine(end + timedelta(days=1), time.min)
    return list(
        session.exec(
            select(PriceBar)
            .where(
                PriceBar.instrument_id == instrument_of(ticker),
                PriceBar.interval == "1d",
                col(PriceBar.ts) >= lower,
                col(PriceBar.ts) < upper,
            )
            .order_by(col(PriceBar.ts))
        ).all()
    )


def execute_strategy(
    session: Session, body: StrategyBacktestIn, *, user_id: int | None
) -> StrategyRun:
    """Raises ``StrategyNotFound``, ``StrategyNeedsUser``, ``StrategyError``
    or ``RuleError``."""
    if body.from_ > body.to:
        raise StrategyError("'from' must be on or before 'to'")
    rules = [_resolve_rule(session, body.entry, "entry", user_id)]
    if body.exit is not None:
        rules.append(_resolve_rule(session, body.exit, "exit", user_id))
    tickers, source = _universe(session, body, user_id)

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
            f"A basket must trade in one currency (got {listed}); split it by market or currency"
        )
    currency = currencies[tickers[0]]
    try:
        check_fee_currency(body.fee_schedule, currency)
    except BacktestError as exc:
        raise StrategyError(str(exc)) from exc

    short = body.direction == "short"
    if short:
        declared = {t.strip().upper() for t in body.shortable}
        for ticker in tickers:
            if ticker not in declared:
                raise StrategyError(
                    f"{ticker} is not declared shortable: list it in 'shortable' to short it"
                )
            if currencies[ticker] != "USD" or venue_for_ticker(ticker) != NEW_YORK_VENUE:
                raise StrategyError(
                    f"{ticker} is not US-listed: shorts are US only (Indian shorts wait "
                    "for the F&O-eligible list)"
                )

    s = body.stops
    stops = Stops(
        fixed_pct=s.fixed_pct,
        atr_multiple=s.atr.multiple if s.atr else None,
        atr_period=s.atr.period if s.atr else 14,
        trail_kind=s.trailing.kind if s.trailing else None,
        trail_value=s.trailing.value if s.trailing else None,
        trail_period=s.trailing.period if s.trailing else 14,
        time_bars=s.time_bars,
    )
    sizing = Sizing(
        kind=body.sizing.kind,
        fraction=body.sizing.fraction,
        risk_pct=body.sizing.risk_pct,
        max_positions=body.sizing.max_positions,
    )
    if sizing.kind == "fixed_risk" and not stops.has_price_stop:
        raise StrategyError("fixed_risk sizing needs a fixed, ATR or trailing stop")

    atr_rules = {p: compile_rule(f"atr({p})", require_condition=False) for p in stops.atr_periods()}
    lookbacks = [r.compiled.lookback for r in rules] + [a.lookback for a in atr_rules.values()]
    lookback = None if any(lb is None for lb in lookbacks) else max(lb or 0 for lb in lookbacks)
    needs = Needs(
        benchmark=any(r.compiled.needs.benchmark for r in rules),
        fundamentals=any(r.compiled.needs.fundamentals for r in rules),
        news=any(r.compiled.needs.news for r in rules),
        delivery=any(r.compiled.needs.delivery for r in rules),
        drawings=any(r.compiled.needs.drawings for r in rules),
    )
    entry_rule = rules[0].compiled
    exit_rule = rules[1].compiled if len(rules) > 1 else None

    inputs: list[SymbolInput] = []
    digest = hashlib.sha256()
    bases: set[str] = set()
    bar_count = 0
    first_at: datetime | None = None
    last_at: datetime | None = None
    for ticker in tickers:
        data = load_symbol(
            session, ticker, end=body.to, start=body.from_, lookback=lookback,
            needs=needs, user_id=user_id,
        )  # fmt: skip
        dates = data.dates
        if not dates:
            continue
        venue = venue_for_ticker(ticker)
        rows = [r for r in _price_rows(session, ticker, dates[0], body.to)
                if bar_date(r.ts, venue) >= dates[0]]  # fmt: skip
        if [bar_date(r.ts, venue) for r in rows] != dates:
            raise StrategyError(f"{ticker}: the bars changed while loading; run it again")
        first = next((i for i, d in enumerate(dates) if d >= body.from_), len(dates))
        if first >= len(dates):
            continue
        entry = _bool_list(vector(entry_rule, data))
        exit_ = _bool_list(vector(exit_rule, data)) if exit_rule is not None else None
        atr = {p: _float_list(vector(rule, data)) for p, rule in atr_rules.items()}
        inputs.append(
            SymbolInput(
                ticker=ticker,
                dates=dates,
                ts=[as_aware_utc(r.ts) for r in rows],
                open=[r.open for r in rows],
                high=[r.high for r in rows],
                low=[r.low for r in rows],
                close=[r.close for r in rows],
                volume=[Decimal(r.volume) for r in rows],
                entry=entry,
                exit=exit_,
                atr=atr,
                first=first,
            )
        )
        digest.update(f"symbol|{ticker}\n".encode())
        for r in rows:
            digest.update(
                f"{r.ts.isoformat()}|{r.open}|{r.high}|{r.low}|{r.close}|{r.volume}|"
                f"{r.adjustment_semantics}\n".encode()
            )
            bases.add(str(r.adjustment_semantics))
        for name in ("delivery_pct", "deliverable_qty"):
            digest.update(f"{name}|{data.bars[name].tolist()!r}\n".encode())
        if data.benchmark is not None:
            digest.update(
                f"bench|{data.benchmark_ticker}|"
                f"{list(zip(data.benchmark.index.strftime('%Y-%m-%d'), data.benchmark.tolist(), strict=True))!r}\n".encode()
            )
        for part in ("fundamentals", "news", "drawings"):
            value = getattr(data, part)
            if value is not None:
                digest.update(f"{part}|{value!r}\n".encode())
        bar_count += len(rows)
        first_at = rows[0].ts if first_at is None else min(first_at, rows[0].ts)
        last_at = rows[-1].ts if last_at is None else max(last_at, rows[-1].ts)

    profile = FILL_RULES[body.fill_rule]
    costs = CostModel(
        spread_bps=Decimal(str(body.spread_bps)), slippage_bps=Decimal(str(body.slippage_bps))
    )
    result = run_strategy(
        inputs,
        initial_cash=body.initial_cash,
        stops=stops,
        sizing=sizing,
        profile=profile,
        costs=costs,
        schedule=get_fee_schedule(body.fee_schedule),
        commission_bps=Decimal(str(body.commission_bps)),
        short=short,
    ) if inputs else None  # fmt: skip

    rules_out = [
        StrategyRuleOut(
            role=r.role,  # type: ignore[arg-type]
            text=r.compiled.text,
            canonical=r.compiled.canonical_text,
            hash=r.compiled.hash,
            setup_version_id=r.version_id,
            warmup_bars=r.compiled.lookback,
        )
        for r in rules
    ]
    notes = [
        "Signals are the rules' vector mode on each completed bar; orders fill on the next "
        f"bar ({profile.name}/{profile.model_version}) through the execution kernel and SimLedger.",
        "Price return: dividends are not credited in rule strategies.",
        "Whole shares only. Positions open at the end are marked at the last close, not sold.",
    ]
    loaded = {i.ticker for i in inputs}
    missing = [t for t in tickers if t not in loaded]
    if missing:
        notes.append(f"No bars in the range for: {', '.join(missing)}.")
    if result is not None and result.skip_reasons:
        words = {"no_slot": "no free slot", "no_cash": "not enough cash for one share",
                 "atr_unknown": "ATR unknown at the signal bar"}  # fmt: skip
        notes.append(
            "Entries skipped: "
            + ", ".join(f"{n} ({words[k]})" for k, n in result.skip_reasons.items())
            + "."
        )

    cash = body.initial_cash
    if result is None:
        trades: list[StrategyTradeOut] = []
        curve: list[EquityPointOut] = []
        summary = StrategySummaryOut(total_return=0.0, sharpe=0.0, max_drawdown=0.0,
                                     final_nav=cash, benchmark_final_nav=cash,
                                     gross_final_nav=cash)  # fmt: skip
        bench_return, bench_final = 0.0, cash
        symbols_out: list[StrategySymbolOut] = []
        unknown_entry = unknown_exit = ignored = 0
        skip_reasons: dict[str, int] = {}
    else:
        trades = [
            StrategyTradeOut(
                ticker=t.ticker,
                direction=t.direction,  # type: ignore[arg-type]
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
                reason=t.reason,  # type: ignore[arg-type]
                gap=t.gap,
                open=t.open,
                bars_held=t.bars_held,
                initial_stop=t.initial_stop,
                initial_risk=t.initial_risk,
                r_multiple=t.r_multiple,
            )
            for t in result.trades
        ]
        curve = [EquityPointOut(date=d, nav=nav) for d, nav in result.equity_curve]
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
        symbols_out = [
            StrategySymbolOut(
                ticker=x.ticker,
                bars=x.bars,
                warmup_bars=x.warmup_bars,
                unknown_entry_bars=x.unknown_entry_bars,
                unknown_exit_bars=x.unknown_exit_bars,
                trades=x.trades,
            )
            for x in result.symbols
        ]
        unknown_entry = sum(x.unknown_entry_bars for x in result.symbols)
        unknown_exit = sum(x.unknown_exit_bars for x in result.symbols)
        ignored = result.ignored_entry_signals
        skip_reasons = result.skip_reasons

    out = StrategyBacktestOut(
        tickers=tickers,
        currency=currency,
        price_basis=None if not bases else bases.pop() if len(bases) == 1 else "mixed",
        execution_profile=f"{profile.name}/{profile.model_version}",
        fee_schedule=body.fee_schedule,
        direction=body.direction,
        rules=rules_out,
        stops=body.stops,
        sizing=body.sizing,
        stop_priority=STOP_PRIORITY,
        trades=trades,
        equity_curve=curve,
        summary=summary,
        benchmark=StrategyBenchmarkOut(
            kind="buy_and_hold" if len(tickers) == 1 else "equal_weight_buy_and_hold",
            tickers=[i.ticker for i in inputs],
            total_return=bench_return,
            final_nav=bench_final,
        ),
        source=source,
        universe=universe_for(tickers[0]),
        warmup_bars=max((i.first for i in inputs), default=0),
        unknown_entry_bars=unknown_entry,
        unknown_exit_bars=unknown_exit,
        ignored_entry_signals=ignored,
        skipped_entries=sum(skip_reasons.values()),
        skip_reasons=skip_reasons,
        symbols=symbols_out,
        strategy_hash=_strategy_hash(body, rules, tickers),
        data_fingerprint=digest.hexdigest(),
        notes=notes,
    )
    return StrategyRun(
        out=out,
        fingerprint=out.data_fingerprint,
        bar_count=bar_count,
        first_bar_at=first_at,
        last_bar_at=last_at,
        entry_version_id=rules[0].version_id,
    )


def materialize_rules(
    session: Session, body: StrategyBacktestIn, user_id: int
) -> StrategyBacktestIn:
    """Inline rule text becomes a version of the user's "Rules from
    backtests" setup (one setup, a version per distinct rule; the same rule
    is the same version), so a saved run always points at a version."""

    def version_for(ref: StrategyRuleIn | None) -> StrategyRuleIn | None:
        if ref is None or ref.rule is None:
            return ref
        compiled = compile_rule(ref.rule)
        setup = session.exec(
            select(Setup).where(
                col(Setup.user_id) == user_id,
                col(Setup.kind) == "strategy",
                col(Setup.name) == INLINE_SETUP_NAME,
                col(Setup.archived_at).is_(None),
            )
        ).first()
        if setup is None:
            _setup, version = store.create_setup(
                session, user_id, name=INLINE_SETUP_NAME, kind="strategy", rule=compiled,
                description="Inline rules from saved backtests; one version per rule.",
            )  # fmt: skip
        else:
            version = store.add_version(session, setup, compiled).version
        assert version.id is not None
        return StrategyRuleIn(setup_version_id=version.id)

    return body.model_copy(
        update={"entry": version_for(body.entry), "exit": version_for(body.exit)}
    )


def request_json(body: StrategyBacktestIn) -> dict[str, Any]:
    return body.model_dump(mode="json", by_alias=True)


__all__ = [
    "INLINE_SETUP_NAME",
    "StrategyNeedsUser",
    "StrategyNotFound",
    "StrategyRun",
    "execute_strategy",
    "materialize_rules",
    "request_json",
]
