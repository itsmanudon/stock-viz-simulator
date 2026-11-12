"""Phase 5.1: a floor on kernel + SimLedger throughput.

Measured locally on 12 Nov 2026: about 146,000 fills a second. The floor is
about 14 times lower, so only a large regression fails (CI runners are slower
and noisier than a laptop).
"""

from stockviz.benchmarks.kernel import run

FLOOR_FILLS_PER_SECOND = 10_000


def test_kernel_and_ledger_keep_their_speed() -> None:
    result = run(bars=20_000)
    assert result.fills_per_second > FLOOR_FILLS_PER_SECOND, result
