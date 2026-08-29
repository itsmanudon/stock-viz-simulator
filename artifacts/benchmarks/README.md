# Benchmark outputs

`scripts/k8s/run-benchmark.sh` writes the rolling `kafka-scaling.json` after a
real kind/CI run. That filename stays gitignored.

`kafka-scaling-100k.json` is the preserved portfolio experiment: 100,000
events at 1, 2, 4, and 8 consumer replicas. It is committed only after
`stockviz.benchmarks.report` validates every hard gate. The throughput chart
and Markdown tables are generated from this file rather than retyped.

The methodology and (when a run happened) interpretation live in
[`docs/KAFKA_SCALING.md`](../../docs/KAFKA_SCALING.md).
