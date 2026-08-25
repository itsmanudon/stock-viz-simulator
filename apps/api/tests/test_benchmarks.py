from stockviz.benchmarks.kafka_scaling import _symbol
from stockviz.benchmarks.topics import BENCHMARK_PARTITIONS, BENCHMARK_TOPIC


def test_benchmark_keys_cover_a_thousand_symbols() -> None:
    keys = {_symbol(i) for i in range(5_000)}
    assert len(keys) == 1000
    assert "SYM0000" in keys
    assert "SYM0999" in keys


def test_benchmark_topic_is_not_a_domain_topic() -> None:
    assert BENCHMARK_TOPIC.startswith("stockviz.benchmark")
    assert BENCHMARK_PARTITIONS == 12
