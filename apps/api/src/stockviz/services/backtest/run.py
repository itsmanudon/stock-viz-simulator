"""Load the data for a backtest request and run it (Phase 5.4).

The public ``POST /v1/backtest`` and the experiment registry both call
``execute_backtest``, so a saved run and an ad-hoc run are the same code. It
also returns the **dataset fingerprint**: a SHA-256 over every bar
(timestamp, OHLC, basis) and dividend the run read, warm-up included. Two
runs with the same request and fingerprint must give the same result; a
rerun refuses to compare when the fingerprint changed.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, time
from decimal import Decimal

from sqlmodel import Session, select

from stockviz.models import Dividend, PriceBar, Symbol
from stockviz.schemas import (
    BacktestFeeOut,
    BacktestIn,
    BacktestOut,
    BacktestSummaryOut,
    BacktestTradeOut,
    EquityPointOut,
    RsiThresholdStrategy,
    SmaCrossoverStrategy,
)
from stockviz.services.backtest import report_card
from stockviz.services.backtest.engine import (
    FILL_RULES,
    BacktestError,
    run_backtest,
    warmup_bars_for,
)
from stockviz.services.backtest.report import SharpeStats
from stockviz.services.backtest.trials import split_window
from stockviz.services.backtest.universe import universe_for
from stockviz.services.fee_view import costs_out, is_indian, liquidity_out, resolve_fee_schedule
from stockviz.services.instruments import instrument_of
from stockviz.services.simulation import get_fee_schedule


class UnknownSymbol(LookupError):
    pass


class BadRange(ValueError):
    pass


@dataclass(frozen=True)
class BacktestRun:
    out: BacktestOut
    fingerprint: str
    bar_count: int
    first_bar_at: datetime | None
    last_bar_at: datetime | None
    stats: SharpeStats | None = None


def strategy_of(body: BacktestIn) -> tuple[str, dict]:
    if isinstance(body.strategy, RsiThresholdStrategy):
        return "rsi_threshold", {
            "buy_below": body.strategy.buy_below,
            "sell_above": body.strategy.sell_above,
        }
    if isinstance(body.strategy, SmaCrossoverStrategy):
        return "sma_crossover", {
            "short_window": body.strategy.short_window,
            "long_window": body.strategy.long_window,
        }
    raise ValueError("Unsupported strategy type")  # pragma: no cover


def fingerprint(bars: list[PriceBar], dividends: dict, *, volume: bool = False) -> str:
    """``volume``: the run read volumes too (A4.2's ADV cap), so they are part
    of its data. Runs without the cap hash exactly as before A4.2."""
    digest = hashlib.sha256()
    for bar in bars:
        tail = f"|{bar.volume}" if volume else ""
        digest.update(
            f"{bar.ts.isoformat()}|{bar.open}|{bar.high}|{bar.low}|{bar.close}|"
            f"{bar.adjustment_semantics}{tail}\n".encode()
        )
    for ex_date in sorted(dividends):
        digest.update(f"div|{ex_date.isoformat()}|{dividends[ex_date]}\n".encode())
    return digest.hexdigest()


def load_bars(
    session: Session, ticker: str, start: datetime, end: datetime, warmup: int
) -> tuple[list[PriceBar], list[PriceBar]]:
    """Daily bars in [start, end], and up to ``warmup`` bars before start (SR-3)."""
    rows = list(
        session.exec(
            select(PriceBar)
            .where(
                PriceBar.instrument_id == instrument_of(ticker),
                PriceBar.interval == "1d",
                PriceBar.ts >= start,
                PriceBar.ts <= end,
            )
            .order_by(PriceBar.ts.asc())  # type: ignore[attr-defined]
        ).all()
    )
    before = list(
        reversed(
            session.exec(
                select(PriceBar)
                .where(
                    PriceBar.instrument_id == instrument_of(ticker),
                    PriceBar.interval == "1d",
                    PriceBar.ts < start,
                )
                .order_by(PriceBar.ts.desc())  # type: ignore[attr-defined]
                .limit(warmup)
            ).all()
        )
    )
    return rows, before


def load_dividends(session: Session, ticker: str, start, end) -> dict:
    return {
        d.ex_date: d.amount
        for d in session.exec(
            select(Dividend).where(
                Dividend.instrument_id == instrument_of(ticker),
                Dividend.ex_date >= start,
                Dividend.ex_date <= end,
            )
        ).all()
    }


def price_basis_of(bars: list[PriceBar]) -> str | None:
    bases = {str(r.adjustment_semantics) for r in bars}
    return None if not bases else bases.pop() if len(bases) == 1 else "mixed"


def check_fee_currency(fee_schedule: str, currency: str) -> None:
    """A fee schedule is for one currency's market (Phase 5.6)."""
    schedule = get_fee_schedule(fee_schedule)
    if schedule.currency is not None and schedule.currency != currency:
        raise BacktestError(
            f"Fee schedule {fee_schedule!r} is for {schedule.currency} stocks; "
            f"this symbol trades in {currency}"
        )


def execute_backtest(session: Session, body: BacktestIn) -> BacktestRun:
    """Raises ``UnknownSymbol``, ``BadRange`` or ``BacktestError``."""
    ticker = body.ticker.upper()
    symbol = session.get(Symbol, ticker)
    if symbol is None:
        raise UnknownSymbol(f"Symbol {ticker!r} not found")
    if body.from_ > body.to:
        raise BadRange("'from' must be on or before 'to'")
    schedule_name = resolve_fee_schedule(body.fee_schedule, ticker)
    check_fee_currency(schedule_name, symbol.currency or "USD")

    # A4.3: the in-sample range (the last 20% is held out by default).
    window = split_window(body.from_, body.to, body.holdout)
    # Inclusive date range; bars are stored at day granularity (interval 1d).
    start = datetime.combine(window.from_date, time.min)
    end = datetime.combine(window.to_date, time.max)
    strategy_type, params = strategy_of(body)
    rows, warmup = load_bars(session, ticker, start, end, warmup_bars_for(strategy_type, params))
    used = warmup + rows
    price_basis = price_basis_of(used)

    dividends: dict = (
        load_dividends(session, ticker, window.from_date, window.to_date)
        if body.return_mode == "total"
        else {}
    )

    result = run_backtest(
        [(r.ts, r.close) for r in used],
        initial_cash=body.initial_cash,
        strategy_type=strategy_type,
        params=params,
        commission_bps=body.commission_bps,
        slippage_bps=body.slippage_bps,
        trade_from=start,
        dividends=dividends or None,
        opens={r.ts: r.open for r in used},
        fill_rule=body.fill_rule,
        spread_bps=body.spread_bps,
        fee_schedule=schedule_name,
        volumes={r.ts: Decimal(r.volume) for r in used},
        adv_cap_pct=body.adv_cap_pct,
        brokerage=body.brokerage,
    )
    profile = FILL_RULES[body.fill_rule]
    cash = body.initial_cash
    curve = [(p.date, p.nav) for p in result.equity_curve]
    trips = report_card.template_trips(
        [
            (t.date, t.side, t.price, t.shares, sum((a for _, a in t.fees), Decimal(0)))
            for t in result.trades
        ],
        (curve[-1][0], used[-1].close) if curve else None,
    )
    card, stats = report_card.build(
        session,
        ticker=ticker,
        curve=curve,
        trips=trips,
        initial_cash=cash,
        max_drawdown=result.summary.max_drawdown,
    )
    gross_nav = result.summary.final_nav + result.total_fees + result.price_costs
    out = BacktestOut(
        ticker=ticker,
        currency=symbol.currency or "USD",
        price_basis=price_basis,
        return_mode=body.return_mode,
        warmup_bars=len(warmup),
        execution_profile=f"{profile.name}/{profile.model_version}",
        fee_schedule=schedule_name if body.fee_schedule == "auto" else body.fee_schedule,
        trades=[
            BacktestTradeOut(
                date=t.date,
                side=t.side,  # type: ignore[arg-type]
                price=t.price,
                shares=t.shares,
                reference_price=t.reference_price,
                fees=[BacktestFeeOut(name=n, amount=a) for n, a in t.fees],
                requested_shares=t.requested_shares,
            )
            for t in result.trades
        ],
        equity_curve=[EquityPointOut(date=p.date, nav=p.nav) for p in result.equity_curve],
        summary=BacktestSummaryOut(
            total_return=result.summary.total_return,
            sharpe=result.summary.sharpe,
            max_drawdown=result.summary.max_drawdown,
            final_nav=result.summary.final_nav,
            benchmark_return=result.summary.benchmark_return,
            benchmark_final_nav=result.summary.benchmark_final_nav,
            excess_return=result.summary.excess_return,
            total_costs=result.summary.total_costs,
            gross_return=float((gross_nav - cash) / cash),
            gross_final_nav=gross_nav,
            total_fees=result.total_fees,
            price_costs=result.price_costs,
        ),
        universe=universe_for(ticker),
        costs=costs_out(
            requested=body.fee_schedule,
            resolved=schedule_name,
            brokerage=body.brokerage,
            commission_bps=body.commission_bps,
            fee_versions=result.fee_versions,
            fills_before_coverage=result.fills_before_coverage,
            indian=is_indian(ticker),
        ),
        liquidity=liquidity_out(
            body.adv_cap_pct,
            partial=sum(1 for t in result.trades if t.requested_shares is not None),
            skipped=result.adv_skipped,
            unknown=result.adv_unknown,
        ),
        window=window,
        report=card,
    )
    return BacktestRun(
        out=out,
        fingerprint=fingerprint(used, dividends, volume=body.adv_cap_pct is not None),
        bar_count=len(used),
        first_bar_at=used[0].ts if used else None,
        last_bar_at=used[-1].ts if used else None,
        stats=stats,
    )


__all__ = [
    "BacktestRun",
    "BadRange",
    "UnknownSymbol",
    "execute_backtest",
    "load_bars",
    "load_dividends",
    "price_basis_of",
]
