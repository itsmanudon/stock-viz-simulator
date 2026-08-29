# Engineering roadmap

StockViz's core portfolio story—transactional trading, event-driven processing, Kubernetes orchestration, and measured scaling—is complete. Remaining work is intentionally framed as honest production hardening, not another implementation phase.

## If this became a real service

- Move PostgreSQL and Kafka to backed-up, highly available managed services.
- Deploy Kubernetes across multiple nodes/zones and add explicit network/pod security policies.
- Adopt managed secrets and key rotation.
- Add consumer retry/DLQ policy and contract governance.
- Scale consumers from lag with stability/capacity controls rather than CPU alone.
- Add centralized logs, metrics, traces, alerts, dashboards, and defined SLOs.
- Load-test financial and provider paths, exercise disaster recovery, and repeat benchmarks across controlled environments.

## Product/model depth

- Replace end-of-day convenience data with a licensed feed before any real-time claim.
- Model option implied-volatility surfaces, rates, exercise, and multi-currency accounting before treating options as brokerage-grade.
- Add next-open and liquidity models to backtesting and broaden browser e2e coverage.
- Add full account recovery/verification flows before accepting durable public accounts.

None of these capabilities is claimed as implemented. Current constraints are listed in [Known limitations](./KNOWN_LIMITATIONS.md).

## Simulation fidelity

SIM-01 added a pure `legacy_close` execution kernel. SIM-02 and SIM-03 route all live equity paper fills (MARKET, LIMIT, STOP_LOSS, TAKE_PROFIT) through `evaluate_order` without changing `apply_fill` economics or fill realism. SIM-04 persists versioned execution provenance for successful fills. SIM-05 adds `ReplaySession`: a frozen historical ticker/range, a monotonic next-bar clock, and server-owned `PriceBar` snapshots on an isolated book (not live `Trade`). SIM-06 is Replay Lab: a future-blind UI over that session. SIM-07 adds deterministic post-trade forensics (episodes, MAE/MFE, buy-and-hold excess, concentration) and a first-fill-locked decision journal. See [SIMULATION.md](./SIMULATION.md).
