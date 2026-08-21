## What changed

<!-- One or two sentences. What does this do, and why now? -->

## Why

<!-- The problem being solved. Link the issue if there is one. -->

Closes #

## How to verify

<!-- The commands or steps a reviewer runs to see it working. -->

```bash
pnpm lint && pnpm typecheck && pnpm build
pnpm --filter @stockviz/web test
uv --directory apps/api run pytest
```

## Checklist

- [ ] Quality gates pass locally (lint, typecheck, build, both test suites)
- [ ] Schema changes have a migration, and `alembic check` reports no drift
- [ ] New router / page / model / scheduler job / env var is reflected in the
      relevant `CLAUDE.md` (root, `apps/api/`, or `apps/web/`)
- [ ] New authenticated endpoints depend on `UserIdDep`
- [ ] Trading or auth semantics changed? Called out explicitly above

## Notes for the reviewer

<!-- Anything you want a second opinion on, or deliberately left out of scope. -->
