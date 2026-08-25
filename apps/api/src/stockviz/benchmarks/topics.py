"""Benchmark topics are deliberately separate from domain topics.

``stockviz.market.v1`` has 3 partitions so production-like consumer HPA
caps at 3. The benchmark topic has 12 partitions so 1/2/4/8 replica runs
can actually share work. Raising a keyed domain topic's partition count
would reshuffle key→partition mapping; we do not do that here.
"""

BENCHMARK_TOPIC = "stockviz.benchmark.v1"
BENCHMARK_RESULTS_TOPIC = "stockviz.benchmark-results.v1"
BENCHMARK_PARTITIONS = 12
BENCHMARK_CONSUMER_GROUP_PREFIX = "stockviz.benchmark."
