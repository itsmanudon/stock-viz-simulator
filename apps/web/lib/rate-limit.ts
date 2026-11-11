/**
 * Throttling for credential auth.
 *
 * `bcrypt.compare` with no attempt counter is an open door: an attacker can
 * grind a password list against `loginAction` as fast as the server will
 * answer. The API has slowapi in front of its public reads, but the Next.js
 * server actions had nothing.
 *
 * Fixed-window counters kept in Postgres (`auth_rate_limits`, schema owned by
 * the API's Alembic chain; audit OP-8). They used to live in this process's
 * memory, so every time the web service slept (Railway `sleepApplication`) the
 * counters vanished, and a second instance would have had its own. One atomic
 * upsert per attempt starts a new window or counts into the current one. The
 * API's nightly `prune-events` deletes windows that ended a day ago.
 *
 * Tests swap in the in-memory store with `clearAll()`.
 */

import "server-only";

import { pool } from "./db";

export type RateLimitResult = {
  allowed: boolean;
  /** Seconds until the window resets. Only meaningful when `allowed` is false. */
  retryAfterSeconds: number;
};

type Store = {
  hit(key: string, limit: number, windowMs: number): Promise<RateLimitResult>;
  reset(key: string): Promise<void>;
};

function verdict(count: number, limit: number, resetAtMs: number, now: number): RateLimitResult {
  if (count > limit) {
    return { allowed: false, retryAfterSeconds: Math.max(1, Math.ceil((resetAtMs - now) / 1000)) };
  }
  return { allowed: true, retryAfterSeconds: 0 };
}

const postgresStore: Store = {
  async hit(key, limit, windowMs) {
    const result = await pool.query<{ count: number; reset_at: Date; now: Date }>(
      `INSERT INTO auth_rate_limits (key, count, reset_at)
       VALUES ($1, 1, now() + $2 * interval '1 millisecond')
       ON CONFLICT (key) DO UPDATE SET
         count = CASE WHEN auth_rate_limits.reset_at <= now() THEN 1
                      ELSE auth_rate_limits.count + 1 END,
         reset_at = CASE WHEN auth_rate_limits.reset_at <= now() THEN EXCLUDED.reset_at
                         ELSE auth_rate_limits.reset_at END
       RETURNING count, reset_at, now() AS now`,
      [key, windowMs],
    );
    const row = result.rows[0];
    return verdict(row.count, limit, row.reset_at.getTime(), row.now.getTime());
  },
  async reset(key) {
    await pool.query("DELETE FROM auth_rate_limits WHERE key = $1", [key]);
  },
};

function memoryStore(): Store {
  const buckets = new Map<string, { count: number; resetAt: number }>();
  return {
    async hit(key, limit, windowMs) {
      const now = Date.now();
      const existing = buckets.get(key);
      if (!existing || existing.resetAt <= now) {
        buckets.set(key, { count: 1, resetAt: now + windowMs });
        return { allowed: true, retryAfterSeconds: 0 };
      }
      existing.count += 1;
      return verdict(existing.count, limit, existing.resetAt, now);
    },
    async reset(key) {
      buckets.delete(key);
    },
  };
}

let store: Store = postgresStore;

/**
 * Record an attempt against `key`. Returns whether it is allowed.
 *
 * @param limit   attempts permitted per window
 * @param windowMs length of the fixed window
 */
export function hit(key: string, limit: number, windowMs: number): Promise<RateLimitResult> {
  return store.hit(key, limit, windowMs);
}

/** Drop a key's window. */
export function reset(key: string): Promise<void> {
  return store.reset(key);
}

/** Test seam: an empty in-memory store in place of Postgres. */
export function clearAll(): void {
  store = memoryStore();
}
