# StockViz interview guide

This is a code-grounded walkthrough for discussing the project. It distinguishes implemented behavior from production improvements that are not in the repository.

## 30-second explanation

StockViz is a full-stack market analytics and paper-trading application. Its financial ledger uses PostgreSQL transactions and row locks for strong consistency, while a transactional outbox, Kafka, idempotent workers, and Kubernetes handle durable asynchronous market, news, and activity processing. I validated the full stack on kind and measured a 100,000-event consumer scaling matrix.

## 2-minute architecture walkthrough

The browser uses a Next.js application for pages, authentication, and server-side authenticated API calls. FastAPI owns the application endpoints and PostgreSQL is the source of truth for users, market data, portfolios, orders, positions, and trades.

The financial path is synchronous. A trade locks its portfolio, validates cash or shares after reservations, updates the ledger, and inserts a `trade.executed` outbox row in the same database transaction. HTTP success follows the commit; Kafka is not required for correctness.

The asynchronous path begins with that outbox. A publisher claims rows safely, publishes to Kafka, and marks them published only after broker acknowledgement. Consumers use stable groups, commit their database work before offsets, and record a durable inbox key so replay is harmless. A singleton scheduler also writes durable market/news refresh requests to the outbox. Ingestion workers call providers, then atomically persist returned data and downstream domain events. Analytics and sentiment workers build derived state; scheduled reconciliation repairs drift.

The Kubernetes lab runs API and web Deployments, a migration Job, singleton scheduler, publisher, independent worker Deployments, PostgreSQL for local/CI, and Strimzi Kafka. It demonstrates orchestration and scaling mechanics on kind, not a cloud production deployment.

## Why PostgreSQL is the source of truth

Cash, positions, reservations, orders, and trades have multi-row invariants that need one atomic decision. PostgreSQL supplies row-level locking, constraints, isolation, rollback, and a consistent read model. Kafka is excellent for distributing committed facts, but it is not used as the ledger or the arbiter of buying power.

## Why not execute trades through Kafka

Putting the command on Kafka would make the HTTP result asynchronous and complicate reservation conflicts, user-visible failure, retries, and read-your-write behavior. StockViz is paper trading, so a synchronous database transaction gives the clearest correctness boundary: either every ledger mutation and the event intent commit, or none do.

## Transactional outbox and the dual-write problem

A naive flow could commit the trade in PostgreSQL and then fail to publish Kafka, leaving downstream systems unaware. Reversing the order can publish an event for a database transaction that later rolls back. StockViz inserts the outbox row inside the ledger transaction. A separate publisher can retry until Kafka acknowledges, so the committed intent is durable without a distributed transaction.

## Why delivery is at least once

The publisher marks `published_at` only after broker acknowledgement. If it crashes after the acknowledgement but before that update, the row remains eligible and can be published again. This is intentional at-least-once behavior; the project does not claim exactly once.

## Consumer idempotency

Each consumer writes an event identifier into `consumer_inbox` in the same PostgreSQL transaction as its derived-state change. A duplicate conflicts with the existing inbox key and skips the side effect. The consumer commits its Kafka offset only after the database transaction succeeds.

## Why Kafka key = portfolio_id for trades

Kafka only orders records within a partition. A stable `portfolio_id` key routes one portfolio's events to one partition, preserving meaningful per-portfolio order while allowing different portfolios to process concurrently.

## Why key = ticker for market/news

Analytics and sentiment care about the sequence of updates for one symbol. A ticker key retains that local order while distributing unrelated symbols across partitions.

## Why three partitions on domain topics

Three partitions are enough to demonstrate independent consumers and bounded horizontal scaling for the current small universe without pretending this lab needs production capacity. The market-ingest HPA therefore caps at three; a fourth replica in the group would be idle.

## Why the benchmark topic uses twelve

The experiment needs 1, 2, 4, and 8 replicas all to receive partitions. A separate 12-partition synthetic topic creates that ceiling without changing domain partitioning or reshuffling domain keys.

## Why 2 replicas can be slower than 1

New replicas trigger group startup and partition assignment; they also share broker, node, CPU, and network resources. For a short or noisy workload, coordination costs can exceed the parallelism benefit. In the measured 100,000-event run, two were faster than one, but eight were slower than four—an example of the same diminishing-return principle.

## What happens if Kafka goes down

Trading can still commit because the ledger and outbox share PostgreSQL. Outbox rows accumulate unpublished and the publisher retries when Kafka returns. Asynchronous ingestion requests and derived activity stop progressing, but Kafka downtime does not corrupt cash or positions. `/health` deliberately does not require the broker.

## What happens if PostgreSQL goes down

Financial writes fail and do not return success. The readiness endpoint fails because the API cannot serve its source-of-truth workload; liveness remains a process check so Kubernetes does not restart a healthy process merely because a dependency is unavailable. Database-backed publisher and worker effects also pause and retry.

## Consumer crashes after DB commit but before offset commit

Kafka redelivers the record. The existing `consumer_inbox` key identifies it as already applied, so the consumer skips the duplicate effect and can commit the offset safely.

## Publisher crashes after Kafka ack but before published_at

The outbox row is still unpublished and is sent again after restart. That duplicate is expected; inbox idempotency prevents repeated derived-state changes.

## Why the scheduler is a singleton Deployment

The Kubernetes API replicas must not each enqueue the same schedules. A dedicated one-replica Deployment gives scheduling an explicit lifecycle and removes it from request-serving pods. PostgreSQL advisory locks remain defense in depth for jobs that must not overlap.

## Why migrations are a Job

Schema changes must complete once before application rollouts proceed. A Job has completion semantics, visible failure, logs, and a clear deployment gate; running Alembic independently in every API replica would race and blur startup failures.

## Why /health is not liveness

`/health` is readiness: it verifies PostgreSQL because a pod without its source of truth should not receive traffic. `/live` only confirms that the process can answer. Making liveness depend on PostgreSQL would create restart storms during a database outage without repairing the dependency.

## Why CPU HPA is imperfect for Kafka

A consumer can be blocked on the broker, PostgreSQL, or an external provider while CPU stays low and lag rises. CPU HPA is useful for demonstrating Kubernetes scaling mechanics in kind, but production consumer autoscaling would normally use lag plus stabilization and capacity safeguards. KEDA is one possible future option, not an implemented component.

## What would change in a real production deployment

I would use managed or HA PostgreSQL with backups and multi-zone failover; managed or multi-broker Kafka with appropriate replication; a cloud multi-node Kubernetes platform; a managed secret store; centralized logs, metrics, traces, dashboards, and alerts; lag-based worker autoscaling; tested disaster recovery; network and pod security policies; provider rate-limit controls; load and failure testing; and explicit SLOs. None of those production capabilities is claimed by this repository.
