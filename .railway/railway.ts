import { defineRailway, github, group, postgres, preserve, project, service } from "railway/iac";

/**
 * StockViz on Railway — lean, low-idle-cost topology.
 *
 * Four resources: managed Postgres, the FastAPI app (always on), the Next.js
 * web app (sleeps on idle), and one nightly cron service that runs the
 * end-of-day refresh through the `stockviz.cli` job twins — the same service
 * code the Kafka workers run, called synchronously, so no broker is needed to
 * host the site. The full event-driven stack still lives in
 * `docker-compose --profile events` and `infra/k8s/` for demonstrating that
 * architecture; it just doesn't run 24/7 here.
 *
 * `api` does NOT sleep: every web page is server-rendered and fetches the API
 * over the private network, and Railway answers a private request to a
 * sleeping service with a 503 rather than waking it — so a sleeping api makes
 * `/markets`, `/stocks/*` and the home page fail on the first hit. web still
 * sleeps (it is the heavier container) and its cold start is self-contained.
 *
 * Secrets are NOT in source. After the first apply, set with `railway variable set`:
 *   - INTERNAL_API_TOKEN   on `api` AND `web` (identical; signs the web->api HS256 bridge)
 *   - AUTH_SECRET          on `web` (NextAuth session signing)
 *   - `cron` needs no manual step: it reads `api`'s INTERNAL_API_TOKEN through a
 *     Railway reference. It never signs anything, but `stockviz.settings` refuses
 *     to load in production while the token still has its committed dev default.
 *   - optional: ALPHA_VANTAGE_KEY, NEWSDATA_KEY, ANTHROPIC_API_KEY,
 *     GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET, SENTRY_DSN, NEXT_PUBLIC_SENTRY_DSN
 *
 * Two-pass wiring: `NEXT_PUBLIC_API_URL` is baked into the web image at build
 * from `${{api.RAILWAY_PUBLIC_DOMAIN}}`, which exists only after a public
 * domain is attached. After the first apply:
 *   1) railway domain --service api   &&   railway domain --service web
 *   2) railway redeploy --service web   (rebuilds with the resolved URL)
 */

const REPO = "itsmanudon/stock-viz-simulator";
const BRANCH = "main";

// Cross-service refs use raw Railway template syntax — the DSL's `svc.env.X`
// handles are objects, not strings, so they can't be embedded in a template
// literal. `${{name.VAR}}` is resolved by Railway at deploy time.
const API_PRIVATE_URL = "http://${{api.RAILWAY_PRIVATE_DOMAIN}}:${{api.PORT}}";
const API_PUBLIC_URL = "https://${{api.RAILWAY_PUBLIC_DOMAIN}}";
const WEB_PUBLIC_URL = "https://${{web.RAILWAY_PUBLIC_DOMAIN}}";
const API_INTERNAL_TOKEN = "${{api.INTERNAL_API_TOKEN}}";

const API_WATCH = ["apps/api/**"];
const WEB_WATCH = ["apps/web/**", "package.json", "pnpm-lock.yaml", "pnpm-workspace.yaml"];

// Nightly end-of-day refresh. `_cmd_ingest` needs an explicit ticker list, so
// enumerate active symbols the same way scheduler.daily_price_refresh does.
//
// The run must FAIL when a step fails. Every step used to end in `|| true`,
// which made Railway report SUCCESS on nights when nothing ran at all. Now:
//   - migrations and the ticker lookup are prerequisites: a failure stops the run;
//   - each job still runs even if an earlier one failed, but a failure is
//     remembered and the run exits 1 at the end;
//   - `news` exits 2 when NEWSDATA_KEY is unset. That is a deliberate skip, not
//     a failure, so only that exit code is tolerated.
// The command is wrapped in `sh -c '...'` below: no single quotes in here.
const job = (command: string) => `${command} || rc=1`;
const EOD_REFRESH = [
  "rc=0",
  "alembic upgrade head || exit 1",
  'TICKERS=$(python -c "from stockviz.db import engine; from sqlmodel import Session, select; from stockviz.models import Symbol; print(\\" \\".join(Session(engine).exec(select(Symbol.ticker).where(Symbol.is_active)).all()))") || exit 1',
  job("python -m stockviz.cli ingest $TICKERS"),
  job("python -m stockviz.cli fx"),
  // Aegis News copy (Phase 2). Exit 2 means it is not configured yet: skip.
  "python -m stockviz.cli aegis-sync || [ $? -eq 2 ] || rc=1",
  "python -m stockviz.cli news || [ $? -eq 2 ] || rc=1",
  job("python -m stockviz.cli score-sentiment"),
  job("python -m stockviz.cli sentiment-aggregate"),
  job("python -m stockviz.cli metrics"),
  job("python -m stockviz.cli dividends"),
  job("python -m stockviz.cli credit-dividends"),
  job("python -m stockviz.cli settle-options"),
  job("python -m stockviz.cli recommend"),
  job("python -m stockviz.cli snapshot-portfolios"),
  // No publisher runs here, so unpublished outbox rows are never sent: clear
  // them after 30 days with the old inbox receipts (audit OP-11).
  job("python -m stockviz.cli prune-events --include-unpublished"),
  "exit $rc",
].join("; ");

export default defineRailway(() => {
  const db = postgres("Postgres");

  const apiSource = github(REPO, { branch: BRANCH, rootDirectory: "apps/api" });
  // Railway auto-detects apps/api/Dockerfile at the root dir; only the watch
  // paths need declaring. Setting builder explicitly here made `config plan`
  // loop forever on a null->DOCKERFILE no-op.
  const apiBuild = { watchPatterns: API_WATCH };
  const pyBase = {
    DATABASE_URL: db.env.DATABASE_URL,
    ENVIRONMENT: "production",
    DEBUG: "false",
  };

  const api = service("api", {
    source: apiSource,
    build: apiBuild,
    env: {
      ...pyBase,
      // Pin the listen port so `${{api.PORT}}` resolves for web's API_URL —
      // Railway's auto-injected PORT is not a referenceable stored variable,
      // and an unpinned `${{api.PORT}}` renders as an empty string.
      PORT: "8080",
      // The cron service owns the scheduled jobs; keep the in-process one off.
      ENABLE_SCHEDULER: "false",
      CORS_ORIGINS: WEB_PUBLIC_URL,
      SENTRY_TRACES_SAMPLE_RATE: "0.1",
      // Set out of band (`railway variable set`); preserve() keeps the value
      // and stops a re-apply from deleting it. Must match web's value.
      INTERNAL_API_TOKEN: preserve(),
    },
    healthcheck: "/health",
    healthcheckTimeout: 30,
    replicas: 1,
    // No `sleepApplication` key: the default is always-on, which is what the
    // api needs (a sleeping api 503s web's server-side render — see header).
    // Setting it explicitly to false made `config plan` loop on a no-op.
  });

  const web = service("web", {
    source: github(REPO, { branch: BRANCH }),
    build: {
      builder: "DOCKERFILE",
      dockerfilePath: "apps/web/Dockerfile",
      watchPatterns: WEB_WATCH,
    },
    env: {
      API_URL: API_PRIVATE_URL,
      NEXT_PUBLIC_API_URL: API_PUBLIC_URL,
      DATABASE_URL: db.env.DATABASE_URL,
      NODE_ENV: "production",
      AUTH_TRUST_HOST: "true",
      // Set out of band; preserve() keeps them across re-applies.
      // INTERNAL_API_TOKEN must equal api's value.
      INTERNAL_API_TOKEN: preserve(),
      AUTH_SECRET: preserve(),
    },
    healthcheck: "/api/health",
    healthcheckTimeout: 30,
    replicas: 1,
    deploy: { sleepApplication: true },
  });

  // Cron: builds once, then Railway runs it on schedule and it exits — billed
  // only for run minutes. 22:00 UTC ≈ 1–2 h after the US close, weekdays.
  const cron = service("cron", {
    source: apiSource,
    build: apiBuild,
    env: {
      ...pyBase,
      // Same value as api, by reference, so there is one secret to rotate.
      // Without it every cron step dies in settings validation (see header).
      INTERNAL_API_TOKEN: API_INTERNAL_TOKEN,
      // No outbox publisher runs on Railway, so the news step skips its
      // article fan-out rather than fill a table nothing reads (audit OP-11).
      EVENTS_OUTBOX_ENABLED: "false",
      // Aegis News sync (Phase 2). All set out of band with `railway variable
      // set --service cron`; preserve() stops a re-apply from deleting them.
      // Until all four of URL, key, issuer and audience are set, aegis-sync
      // exits 2 and the chain skips it. AEGIS_SIGNING_KEY is the Ed25519
      // private key whose public half Aegis lists in AEGIS_OIDC_PUBLIC_KEYS.
      AEGIS_BASE_URL: preserve(),
      AEGIS_SIGNING_KEY: preserve(),
      AEGIS_KEY_ID: preserve(),
      AEGIS_ISSUER: preserve(),
      AEGIS_AUDIENCE: preserve(),
    },
    deploy: {
      cronSchedule: "0 22 * * 1-5",
      startCommand: `sh -c '${EOD_REFRESH}'`,
      restartPolicyType: "NEVER",
    },
  });

  group("App", [api, web, cron]);

  return project("stockviz", {
    resources: [db, api, web, cron],
  });
});
