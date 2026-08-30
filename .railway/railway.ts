import { defineRailway, github, group, postgres, preserve, project, service } from "railway/iac";

/**
 * StockViz on Railway — lean, low-idle-cost topology.
 *
 * Four resources: managed Postgres, the FastAPI app, the Next.js web app (both
 * sleep-on-idle), and one nightly cron service that runs the end-of-day
 * refresh through the `stockviz.cli` job twins — the same service code the
 * Kafka workers run, called synchronously, so no broker is needed to host the
 * site. The full event-driven stack still lives in
 * `docker-compose --profile events` and `infra/k8s/` for demonstrating that
 * architecture; it just doesn't run 24/7 here.
 *
 * Secrets are NOT in source. After the first apply, set with `railway variable set`:
 *   - INTERNAL_API_TOKEN   on `api` AND `web` (identical; signs the web->api HS256 bridge)
 *   - AUTH_SECRET          on `web` (NextAuth session signing)
 *   - INTERNAL_API_TOKEN   on `cron` is not needed (it talks to the DB directly)
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

const API_WATCH = ["apps/api/**"];
const WEB_WATCH = ["apps/web/**", "package.json", "pnpm-lock.yaml", "pnpm-workspace.yaml"];

// Nightly end-of-day refresh. `_cmd_ingest` needs an explicit ticker list, so
// enumerate active symbols the same way scheduler.daily_price_refresh does.
// `|| true` keeps one skipped job (e.g. news with no NEWSDATA_KEY exits 2)
// from aborting the rest.
const EOD_REFRESH = [
  "alembic upgrade head",
  'TICKERS=$(python -c "from stockviz.db import engine; from sqlmodel import Session, select; from stockviz.models import Symbol; print(\\" \\".join(Session(engine).exec(select(Symbol.ticker).where(Symbol.is_active)).all()))")',
  "python -m stockviz.cli ingest $TICKERS || true",
  "python -m stockviz.cli fx || true",
  "python -m stockviz.cli news || true",
  "python -m stockviz.cli score-sentiment || true",
  "python -m stockviz.cli sentiment-aggregate || true",
  "python -m stockviz.cli metrics || true",
  "python -m stockviz.cli dividends || true",
  "python -m stockviz.cli credit-dividends || true",
  "python -m stockviz.cli settle-options || true",
  "python -m stockviz.cli recommend || true",
  "python -m stockviz.cli snapshot-portfolios || true",
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
    deploy: { sleepApplication: true },
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
    env: pyBase,
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
