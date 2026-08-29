# Verification evidence

This directory records reproducible, credential-free verification summaries.
Provider-derived Massive comparison output is private and belongs under the
gitignored `artifacts/private/` tree instead.

## Pre-change baseline (2026-08-29)

- API: 602 passed, 10 skipped (`pytest -q`).
- Web: 231 passed across 39 files (`vitest run`).
- Pre-existing unrelated product failures: none.
- Host note: the first API attempt could not create pytest temporary folders
  under the global Windows temp directory. Re-running with `TEMP` and `TMP`
  scoped beneath the worktree passed; this was an environment permission issue,
  not a StockViz test failure.

No live credentials or provider payloads are stored here.

## Clean source-build verification (2026-08-29)

- Rebuilt `stockviz-api:pipeline-verify`, `stockviz-web:pipeline-verify`, and
  `stockviz-api-tests:pipeline-verify` with `--no-cache` from their Dockerfiles.
- Started isolated Postgres, Kafka, API, and web services; both service health
  probes returned HTTP 200.
- Passed 65 credential-free settings, market, news, outbox, PostgreSQL, and
  Kafka tests, including both market and news/sentiment event roundtrips.
- Recorded local image IDs in the ignored run log.
- Confirmed the isolated containers, network, and Postgres volume were removed.
