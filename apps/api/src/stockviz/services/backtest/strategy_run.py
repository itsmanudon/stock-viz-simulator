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
from stockviz.models.setup import Setup, SetupVersion
from stockviz.models.watchlist import Watchlist, WatchlistItem
from stockviz.schemas import (
    EquityPointOut,
    RotationBacktestIn,
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
from stockviz.services.backtest import report_card
from stockviz.services.backtest.engine import FILL_RULES, BacktestError
from stockviz.services.backtest.report import SharpeStats, Trip
from stockviz.services.backtest.run import check_fee_currency
from stockviz.services.backtest.strategy import (
    STOP_PRIORITY,
    Sizing,
    Stops,
    StrategyError,
    SymbolInput,
    run_strategy,
)
from stockviz.services.backtest.trials import split_window
from stockviz.services.backtest.universe import universe_for
from stockviz.services.bars.intraday import FEED_BADGES
from stockviz.services.bars.resample import bar_date
from stockviz.services.dsl import CompiledRule, Needs, compile_rule, load_symbol, vector
from stockviz.services.fee_view import costs_out, is_indian, liquidity_out, resolve_fee_schedule
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
    stats: SharpeStats | None = None

    @property
    def label(self) -> str:
        tickers = self.out.tickers
        return tickers[0] if len(tickers) == 1 else f"{tickers[0]}+{len(tickers) - 1}"[:16]


@dataclass(frozen=True)
class _Rule:
    role: str
    compiled: CompiledRule
    version_id: int | None


def _resolve_rule(
    session: Session,
    ref: StrategyRuleIn,
    role: str,
    user_id: int | None,
    timeframe: str = "daily",
) -> _Rule:
    """A rule by version or text, for ``timeframe`` (A6.4: a version on other
    bars is a ``StrategyError``; rotations, event studies and drills are daily)."""
    if ref.setup_version_id is not None:
        try:
            version = store.visible_version(session, ref.setup_version_id, user_id)
        except store.SetupNotFound as exc:
            raise StrategyNotFound(f"Setup version {ref.setup_version_id} not found") from exc
        if version.timeframe != timeframe:
            raise StrategyError(
                f"Setup version {version.id} is judged on {version.timeframe} bars; "
                f"this run uses {timeframe} bars"
            )
        compiled = compile_rule(version.rule_text, timeframe=timeframe)
        rule = _Rule(role, compiled, version.id)
    else:
        assert ref.rule is not None
        # RuleError: the router's 422
        rule = _Rule(role, compile_rule(ref.rule, timeframe=timeframe), None)
    if rule.compiled.user_scoped and user_id is None:
        raise StrategyNeedsUser("This rule reads your drawings: sign in to run it")
    return rule


def _universe(
    session: Session, body: StrategyBacktestIn | RotationBacktestIn, user_id: int | None
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
    # A4.2 settings join the hash only when they differ from what a run saved
    # before A4.2 implied, so those runs keep their hash.
    if body.adv_cap_pct is not None:
        payload["adv_cap_pct"] = body.adv_cap_pct
    if body.brokerage != "zerodha":
        payload["brokerage"] = body.brokerage
    # A4.3: the holdout joins only when on, so runs saved before it keep theirs.
    if body.holdout != "none":
        payload["holdout"] = body.holdout
    # A6.4: intraday settings join only off their defaults.
    if body.timeframe != "daily":
        payload["timeframe"] = body.timeframe
        payload["feed"] = body.feed
        payload["flatten_at_close"] = body.flatten_at_close
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
    window = split_window(body.from_, body.to, body.holdout)
    tf = body.timeframe
    intraday = tf != "daily"
    if not intraday and (body.feed != "auto" or body.flatten_at_close):
        raise StrategyError("feed and flatten_at_close are for intraday timeframes")
    rules = [_resolve_rule(session, body.entry, "entry", user_id, tf)]
    if body.exit is not None:
        rules.append(_resolve_rule(session, body.exit, "exit", user_id, tf))
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
    defaults = {resolve_fee_schedule(body.fee_schedule, t) for t in tickers}
    if len(defaults) > 1:
        raise StrategyError(
            "The basket spans markets with different default fee schedules "
            f"({', '.join(sorted(defaults))}); choose one fee schedule"
        )
    schedule_name = defaults.pop()
    try:
        check_fee_currency(schedule_name, currency)
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

    atr_rules = {
        p: compile_rule(f"atr({p})", require_condition=False, timeframe=tf)
        for p in stops.atr_periods()
    }
    lookbacks = [r.compiled.lookback for r in rules] + [a.lookback for a in atr_rules.values()]
    lookback = None if any(lb is None for lb in lookbacks) else max(lb or 0 for lb in lookbacks)
    needs = Needs(
        benchmark=any(r.compiled.needs.benchmark for r in rules),
        fundamentals=any(r.compiled.needs.fundamentals for r in rules),
        news=any(r.compiled.needs.news for r in rules),
        delivery=any(r.compiled.needs.delivery for r in rules),
        drawings=any(r.compiled.needs.drawings for r in rules),
        daily=any(r.compiled.needs.daily for r in rules),
    )
    entry_rule = rules[0].compiled
    exit_rule = rules[1].compiled if len(rules) > 1 else None

    inputs: list[SymbolInput] = []
    digest = hashlib.sha256()
    bases: set[str] = set()
    bar_count = 0
    first_at: datetime | None = None
    last_at: datetime | None = None
    feeds: set[str] = set()
    for ticker in tickers:
        if intraday:
            loaded = _intraday_input(
                session, ticker, body, window, lookback, needs, user_id, entry_rule, exit_rule,
                atr_rules, digest,
            )  # fmt: skip
            if loaded is None:
                continue
            item, feed, rows_n, first_ts, last_ts = loaded
            inputs.append(item)
            feeds.add(feed)
            bar_count += rows_n
            first_at = first_ts if first_at is None else min(first_at, first_ts)
            last_at = last_ts if last_at is None else max(last_at, last_ts)
            continue
        data = load_symbol(
            session, ticker, end=window.to_date, start=window.from_date, lookback=lookback,
            needs=needs, user_id=user_id,
        )  # fmt: skip
        dates = data.dates
        if not dates:
            continue
        venue = venue_for_ticker(ticker)
        rows = [r for r in _price_rows(session, ticker, dates[0], window.to_date)
                if bar_date(r.ts, venue) >= dates[0]]  # fmt: skip
        if [bar_date(r.ts, venue) for r in rows] != dates:
            raise StrategyError(f"{ticker}: the bars changed while loading; run it again")
        first = next((i for i, d in enumerate(dates) if d >= window.from_date), len(dates))
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
            days = pd.DatetimeIndex(data.benchmark.index).strftime("%Y-%m-%d").tolist()
            closes = list(zip(days, data.benchmark.tolist(), strict=True))
            digest.update(f"bench|{data.benchmark_ticker}|{closes!r}\n".encode())
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
    same_day = _same_day_schedule(schedule_name) if intraday else None
    ppy = periods_per_year(tickers[0], tf) if intraday else None
    result = run_strategy(
        inputs,
        initial_cash=body.initial_cash,
        stops=stops,
        sizing=sizing,
        profile=profile,
        costs=costs,
        schedule=get_fee_schedule(schedule_name),
        commission_bps=Decimal(str(body.commission_bps)),
        short=short,
        brokerage=body.brokerage,
        adv_cap_pct=body.adv_cap_pct,
        flatten_at_close=body.flatten_at_close,
        same_day_schedule=get_fee_schedule(same_day) if same_day else None,
        periods_per_year=ppy,
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
    if intraday:
        notes_intraday = [
            f"Intraday: {tf} bars from the stored feed ({', '.join(sorted(feeds)) or 'none'}); "
            "signals on each closed bar, fills on the next bar.",
            "Entries only inside a session: an entry signal on a session's last bar is dropped. "
            + (
                "Positions still open at a session's last bar are sold at its close."
                if body.flatten_at_close
                else "Positions may be held overnight; an exit signalled at the close fills at "
                "the next session's open."
            ),
        ]
        if same_day:
            notes_intraday.append(
                f"Round trips closed in their entry's session are priced on {same_day}."
            )
        if body.adv_cap_pct is not None:
            notes_intraday.append(
                "ADV cap: the 20-session average traded value from daily bars (intraday volume "
                "is not used); entries without 20 earlier daily bars are not capped."
            )
    notes = [
        "Signals are the rules' vector mode on each completed bar; orders fill on the next "
        f"bar ({profile.name}/{profile.model_version}) through the execution kernel and SimLedger.",
        "Price return: dividends are not credited in rule strategies.",
        "Whole shares only. Positions open at the end are marked at the last close, not sold.",
    ]
    if intraday:
        notes.extend(notes_intraday)
    loaded = {i.ticker for i in inputs}
    missing = [t for t in tickers if t not in loaded]
    if missing:
        notes.append(f"No bars in the range for: {', '.join(missing)}.")
    if result is not None and result.skip_reasons:
        words = {"no_slot": "no free slot", "no_cash": "not enough cash for one share",
                 "atr_unknown": "ATR unknown at the signal bar",
                 "adv_cap": "the ADV cap allowed no whole share",
                 "session_end": "signalled on a session's last bar"}  # fmt: skip
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
                **{
                    "entry_date": t.entry_date,
                    "exit_date": t.exit_date,
                    **(_intraday_trade(t, inputs) if intraday else {}),
                },
                ticker=t.ticker,
                direction=t.direction,  # type: ignore[arg-type]
                entry_price=t.entry_price,
                entry_reference_price=t.entry_reference,
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
                requested_quantity=t.requested_quantity,
                exit_adv_pct=t.exit_adv_pct,
            )
            for t in result.trades
        ]
        curve = [
            EquityPointOut(date=d.date(), nav=nav, at=d)
            if intraday and isinstance(d, datetime)
            else EquityPointOut(date=d, nav=nav)
            for d, nav in result.equity_curve
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

    if intraday:
        card, stats = report_card.build(
            session,
            ticker=tickers[0],
            curve=[(p.at or p.date, p.nav) for p in curve],
            trips=[
                Trip(
                    t.entry_at or t.entry_date,
                    t.exit_at or t.exit_date,
                    t.pnl,
                    t.r_multiple,
                    t.open,
                )
                for t in trades
            ],
            initial_cash=cash,
            max_drawdown=summary.max_drawdown,
            periods_per_year=ppy or 252,
            session_days=[p.date for p in curve],
        )
    else:
        card, stats = report_card.build(
            session,
            ticker=tickers[0],
            curve=[(p.date, p.nav) for p in curve],
            trips=[Trip(t.entry_date, t.exit_date, t.pnl, t.r_multiple, t.open) for t in trades],
            initial_cash=cash,
            max_drawdown=summary.max_drawdown,
        )
    out = StrategyBacktestOut(
        tickers=tickers,
        currency=currency,
        price_basis=None if not bases else bases.pop() if len(bases) == 1 else "mixed",
        execution_profile=f"{profile.name}/{profile.model_version}",
        fee_schedule=schedule_name if body.fee_schedule == "auto" else body.fee_schedule,
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
            skipped=result.skip_reasons.get("adv_cap", 0) if result is not None else 0,
            unknown=result.adv_unknown if result is not None else 0,
        ),
        window=window,
        report=card,
        **(
            {
                "timeframe": tf,
                "feed": ",".join(sorted(feeds)) or None,
                "feed_badge": FEED_BADGES.get(next(iter(feeds))) if len(feeds) == 1 else None,
                "flatten_at_close": body.flatten_at_close,
                "periods_per_year": ppy,
            }
            if intraday
            else {}
        ),
    )
    return StrategyRun(
        out=out,
        fingerprint=out.data_fingerprint,
        bar_count=bar_count,
        first_bar_at=first_at,
        last_bar_at=last_at,
        entry_version_id=rules[0].version_id,
        stats=stats,
    )


# --- A6.4: intraday runs -------------------------------------------------------

REGULAR_MINUTES = {"XNSE": 375, "XBOM": 375, "XNYS": 390}
"""A regular session's trading minutes (NSE 09:15-15:30, XNYS 09:30-16:00)."""


def periods_per_year(ticker: str, timeframe: str) -> float:
    """Bars a year on ``timeframe`` for ``ticker``'s venue: bars in a regular
    session (the last one clipped, so rounded up) x 252 sessions."""
    import math

    from stockviz.services.backtest.engine import TRADING_DAYS_PER_YEAR
    from stockviz.services.bars.intraday import INTERVAL_MINUTES

    minutes = REGULAR_MINUTES.get(venue_for_ticker(ticker), 390)
    return float(math.ceil(minutes / INTERVAL_MINUTES[timeframe]) * TRADING_DAYS_PER_YEAR)


def _same_day_schedule(schedule_name: str) -> str | None:
    """The intraday family a delivery schedule's same-day round trips pay."""
    if schedule_name.startswith("in_equity_delivery_"):
        return schedule_name.replace("in_equity_delivery_", "in_equity_intraday_")
    return None


def _venue_midnight(day: date, venue: str) -> datetime:
    """``day``'s start in the venue's zone, as naive UTC."""
    from datetime import UTC

    from stockviz.services.markets.calendar import venue_zone

    aware = datetime.combine(day, time.min, tzinfo=venue_zone(venue))
    return aware.astimezone(UTC).replace(tzinfo=None)


def _daily_adv(session: Session, ticker: str, sessions: list[date]) -> list[Decimal | None]:
    """Per bar: the mean close x volume of the 20 daily bars before its session
    (None with fewer), from ``price_bars`` (the exchange's daily volume)."""
    from stockviz.services.backtest.strategy import ADV_BARS

    if not sessions:
        return []
    venue = venue_for_ticker(ticker)
    rows = _price_rows(session, ticker, sessions[0] - timedelta(days=60), sessions[-1])
    days = [bar_date(r.ts, venue) for r in rows]
    values = [r.close * Decimal(r.volume) for r in rows]
    out: dict[date, Decimal | None] = {}
    import bisect

    for d in sorted(set(sessions)):
        j = bisect.bisect_left(days, d)
        out[d] = sum(values[j - ADV_BARS : j], Decimal(0)) / ADV_BARS if j >= ADV_BARS else None
    return [out[d] for d in sessions]


def _intraday_input(
    session: Session,
    ticker: str,
    body: StrategyBacktestIn,
    window,
    lookback: int | None,
    needs: Needs,
    user_id: int | None,
    entry_rule: CompiledRule,
    exit_rule: CompiledRule | None,
    atr_rules: dict[int, CompiledRule],
    digest,
) -> tuple[SymbolInput, str, int, datetime, datetime] | None:
    """One symbol's intraday bars, signals and ATRs, or None without bars in
    the window. Raises ``StrategyError`` when it has no intraday bars."""
    from stockviz.services.bars.intraday import NoIntradayData
    from stockviz.services.dsl.data import intraday_bars_for, intraday_symbol

    venue = venue_for_ticker(ticker)
    start = _venue_midnight(window.from_date, venue)
    end = _venue_midnight(window.to_date + timedelta(days=1), venue) - timedelta(microseconds=1)
    try:
        feed, bars = intraday_bars_for(
            session, ticker, timeframe=body.timeframe, end=end, start=start,
            lookback=lookback, feed=None if body.feed == "auto" else body.feed,
        )  # fmt: skip
    except NoIntradayData as exc:
        raise StrategyError(str(exc)) from exc
    bars = [b for b in bars if b.session_date <= window.to_date]
    first = next((i for i, b in enumerate(bars) if b.session_date >= window.from_date), len(bars))
    if first >= len(bars):
        return None
    data = intraday_symbol(
        session, ticker, bars, timeframe=body.timeframe, feed=feed, needs=needs, user_id=user_id
    )
    sessions = [b.session_date for b in bars]
    entry = _bool_list(vector(entry_rule, data))
    exit_ = _bool_list(vector(exit_rule, data)) if exit_rule is not None else None
    atr = {p: _float_list(vector(rule, data)) for p, rule in atr_rules.items()}
    item = SymbolInput(
        ticker=ticker,
        dates=[b.ts for b in bars],
        ts=[as_aware_utc(b.ts) for b in bars],
        open=[b.open for b in bars],
        high=[b.high for b in bars],
        low=[b.low for b in bars],
        close=[b.close for b in bars],
        volume=[Decimal(b.volume) for b in bars],
        entry=entry,
        exit=exit_,
        atr=atr,
        first=first,
        sessions=sessions,
        adv=_daily_adv(session, ticker, sessions) if body.adv_cap_pct is not None else None,
    )
    digest.update(f"symbol|{ticker}|{body.timeframe}|{feed}\n".encode())
    for b in bars:
        digest.update(
            f"{b.ts.isoformat()}|{b.open}|{b.high}|{b.low}|{b.close}|{b.volume}|{b.source}\n".encode()
        )
    if data.daily is not None:
        digest.update(f"daily|{data.daily.to_numpy().tolist()!r}\n".encode())
    if data.benchmark is not None:
        digest.update(f"bench|{data.benchmark.tolist()!r}\n".encode())
    for part in ("fundamentals", "news", "drawings"):
        value = getattr(data, part)
        if value is not None:
            digest.update(f"{part}|{value!r}\n".encode())
    if item.adv is not None:
        digest.update(f"adv|{item.adv!r}\n".encode())
    return item, feed, len(bars), bars[0].ts, bars[-1].ts


def _intraday_trade(t, inputs: list[SymbolInput]) -> dict[str, Any]:
    """An intraday trade's instants, session dates and same-day flag."""
    item = next(i for i in inputs if i.ticker == t.ticker)
    assert item.sessions is not None
    index = {d: k for k, d in enumerate(item.dates)}
    entry_day = item.sessions[index[t.entry_date]]
    exit_day = item.sessions[index[t.exit_date]]
    return {
        "entry_at": t.entry_date,
        "exit_at": t.exit_date,
        "entry_date": entry_day,
        "exit_date": exit_day,
        "same_day": not t.open and entry_day == exit_day,
    }


def inline_rule_version(
    session: Session,
    user_id: int,
    compiled: CompiledRule,
    *,
    name: str,
    kind: str,
    description: str,
) -> SetupVersion:
    """Inline rule text as a version of the user's setup ``name`` (one setup,
    a version per distinct rule; the same rule is the same version). A4.1's
    saved backtests and A4.7's drill decks use it."""
    setup = session.exec(
        select(Setup).where(
            col(Setup.user_id) == user_id,
            col(Setup.kind) == kind,
            col(Setup.name) == name,
            col(Setup.archived_at).is_(None),
        )
    ).first()
    if setup is None:
        _setup, version = store.create_setup(
            session, user_id, name=name, kind=kind, rule=compiled, description=description
        )
    else:
        version = store.add_version(session, setup, compiled).version
    return version


def materialize_rules(
    session: Session, body: StrategyBacktestIn, user_id: int
) -> StrategyBacktestIn:
    """Inline rule text becomes a version of the user's "Rules from
    backtests" setup (one setup, a version per distinct rule; the same rule
    is the same version), so a saved run always points at a version."""

    def version_for(ref: StrategyRuleIn | None) -> StrategyRuleIn | None:
        if ref is None or ref.rule is None:
            return ref
        version = inline_rule_version(
            session, user_id, compile_rule(ref.rule), name=INLINE_SETUP_NAME, kind="strategy",
            description="Inline rules from saved backtests; one version per rule.",
        )  # fmt: skip
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
    "inline_rule_version",
    "materialize_rules",
    "request_json",
]
