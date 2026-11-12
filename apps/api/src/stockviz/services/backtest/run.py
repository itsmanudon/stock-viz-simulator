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
from stockviz.services.backtest.engine import FILL_RULES, run_backtest, warmup_bars_for
from stockviz.services.instruments import instrument_of


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


def fingerprint(bars: list[PriceBar], dividends: dict) -> str:
    digest = hashlib.sha256()
    for bar in bars:
        digest.update(
            f"{bar.ts.isoformat()}|{bar.open}|{bar.high}|{bar.low}|{bar.close}|"
            f"{bar.adjustment_semantics}\n".encode()
        )
    for ex_date in sorted(dividends):
        digest.update(f"div|{ex_date.isoformat()}|{dividends[ex_date]}\n".encode())
    return digest.hexdigest()


def execute_backtest(session: Session, body: BacktestIn) -> BacktestRun:
    """Raises ``UnknownSymbol``, ``BadRange`` or ``BacktestError``."""
    ticker = body.ticker.upper()
    symbol = session.get(Symbol, ticker)
    if symbol is None:
        raise UnknownSymbol(f"Symbol {ticker!r} not found")
    if body.from_ > body.to:
        raise BadRange("'from' must be on or before 'to'")

    # Inclusive date range; bars are stored at day granularity (interval 1d).
    start = datetime.combine(body.from_, time.min)
    end = datetime.combine(body.to, time.max)
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
    strategy_type, params = strategy_of(body)

    # Warm-up (audit SR-3): the bars before ``from`` the strategy needs, read
    # but not traded, so its first signal inside the window is a real one.
    warmup = list(
        reversed(
            session.exec(
                select(PriceBar)
                .where(
                    PriceBar.instrument_id == instrument_of(ticker),
                    PriceBar.interval == "1d",
                    PriceBar.ts < start,
                )
                .order_by(PriceBar.ts.desc())  # type: ignore[attr-defined]
                .limit(warmup_bars_for(strategy_type, params))
            ).all()
        )
    )
    used = warmup + rows
    bases = {r.adjustment_semantics for r in used}
    price_basis = None if not bases else bases.pop() if len(bases) == 1 else "mixed"

    dividends: dict = {}
    if body.return_mode == "total":
        dividends = {
            d.ex_date: d.amount
            for d in session.exec(
                select(Dividend).where(
                    Dividend.instrument_id == instrument_of(ticker),
                    Dividend.ex_date >= body.from_,
                    Dividend.ex_date <= body.to,
                )
            ).all()
        }

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
        fee_schedule=body.fee_schedule,
    )
    profile = FILL_RULES[body.fill_rule]
    out = BacktestOut(
        ticker=ticker,
        currency=symbol.currency or "USD",
        price_basis=str(price_basis) if price_basis is not None else None,
        return_mode=body.return_mode,
        warmup_bars=len(warmup),
        execution_profile=f"{profile.name}/{profile.model_version}",
        fee_schedule=body.fee_schedule,
        trades=[
            BacktestTradeOut(
                date=t.date,
                side=t.side,  # type: ignore[arg-type]
                price=t.price,
                shares=t.shares,
                reference_price=t.reference_price,
                fees=[BacktestFeeOut(name=n, amount=a) for n, a in t.fees],
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
        ),
    )
    return BacktestRun(
        out=out,
        fingerprint=fingerprint(used, dividends),
        bar_count=len(used),
        first_bar_at=used[0].ts if used else None,
        last_bar_at=used[-1].ts if used else None,
    )


__all__ = ["BacktestRun", "BadRange", "UnknownSymbol", "execute_backtest"]
