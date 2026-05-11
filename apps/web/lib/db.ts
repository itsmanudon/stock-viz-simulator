/**
 * Postgres pool shared by the auth layer (and any future server-side
 * mutations that talk to the DB directly).
 *
 * We deliberately keep this thin — no ORM, no migrations. Schema is owned by
 * the FastAPI side via Alembic; we just read/write the rows.
 *
 * Singleton-per-process: in dev (HMR) Next.js re-evaluates modules, so cache
 * the pool on globalThis to avoid exhausting connections.
 */

import { Pool } from "pg";

const DEFAULT_URL = "postgres://stockviz:stockviz_dev@127.0.0.1:5434/stockviz";

declare global {
  // eslint-disable-next-line no-var
  var __stockvizPgPool: Pool | undefined;
}

function buildPool(): Pool {
  return new Pool({
    connectionString: process.env.DATABASE_URL ?? DEFAULT_URL,
    max: 5,
    idleTimeoutMillis: 30_000,
  });
}

export const pool: Pool = globalThis.__stockvizPgPool ?? buildPool();
if (process.env.NODE_ENV !== "production") {
  globalThis.__stockvizPgPool = pool;
}
