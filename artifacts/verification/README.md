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
