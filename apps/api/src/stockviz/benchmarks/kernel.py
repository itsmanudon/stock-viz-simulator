"""Kernel + SimLedger throughput (Phase 5.1, performance plan step 1).

Measures what a backtest does per bar: build a snapshot, evaluate one order
with the kernel, apply the fill to a SimLedger. Deterministic inputs (a
seeded walk), no database. ``stockviz.cli benchmark-kernel`` prints the
numbers; ``tests/test_kernel_benchmark.py`` holds a generous floor so a large
regression fails CI on the promotion pull request.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from stockviz.services.simulation import (
    LEGACY_CLOSE,
    MarketSnapshot,
    OrderIntent,
    OrderSide,
    SimLedger,
    SimulationOrderType,
    evaluate_order,
)


@dataclass(frozen=True)
class KernelBenchmark:
    bars: int
    seconds: float

    @property
    def fills_per_second(self) -> float:
        return self.bars / self.seconds if self.seconds else float("inf")


def run(bars: int = 20_000, *, seed: int = 7) -> KernelBenchmark:
    rng = random.Random(seed)
    ledger = SimLedger(cash=Decimal(1_000_000_000))
    start = datetime(2000, 1, 3, tzinfo=UTC)
    price = Decimal(100)
    began = time.perf_counter()
    for i in range(bars):
        price = max(Decimal(1), price + Decimal(rng.randint(-200, 200)) / 100)
        at = start + timedelta(days=i)
        snapshot = MarketSnapshot(
            ticker="BENCH",
            observed_at=at,
            interval="1d",
            open=price,
            high=price + 1,
            low=price - Decimal("0.5"),
            close=price,
            volume=Decimal(1000),
        )
        side = OrderSide.BUY if i % 2 == 0 else OrderSide.SELL
        intent = OrderIntent(
            ticker="BENCH",
            side=side,
            order_type=SimulationOrderType.MARKET,
            quantity=Decimal(1),
            remaining_quantity=Decimal(1),
            submitted_at=at,
        )
        decision = evaluate_order(intent, snapshot, LEGACY_CLOSE)
        if decision.fill_price is not None:
            ledger.apply(side, "BENCH", Decimal(1), decision.fill_price)
    return KernelBenchmark(bars=bars, seconds=time.perf_counter() - began)
