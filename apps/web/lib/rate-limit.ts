/**
 * Throttling for credential auth.
 *
 * `bcrypt.compare` with no attempt counter is an open door: an attacker can
 * grind a password list against `loginAction` as fast as the server will
 * answer. The API has slowapi in front of its public reads, but the Next.js
 * server actions had nothing.
 *
 * This is an in-process fixed-window counter — it holds per instance, not
 * across a horizontally scaled deployment. That is a deliberate first step:
 * it stops the trivial single-origin grind and costs no infrastructure. If the
 * app ever runs more than one web instance, swap `hit()` for a shared store
 * (Upstash/Redis) — the call sites don't change.
 */

import "server-only";

type Window = { count: number; resetAt: number };

declare global {
  // eslint-disable-next-line no-var
  var __stockvizRateLimit: Map<string, Window> | undefined;
}

// Cached on globalThis so Next.js dev HMR doesn't reset the counters on
// every edit (the same reason lib/db.ts caches its pool).
const buckets: Map<string, Window> = globalThis.__stockvizRateLimit ?? new Map();
if (process.env.NODE_ENV !== "production") {
  globalThis.__stockvizRateLimit = buckets;
}

export type RateLimitResult = {
  allowed: boolean;
  /** Seconds until the window resets. Only meaningful when `allowed` is false. */
  retryAfterSeconds: number;
};

function sweep(now: number): void {
  // Bounded cleanup so a stream of unique keys can't grow the map forever.
  if (buckets.size < 10_000) return;
  for (const [key, window] of buckets) {
    if (window.resetAt <= now) buckets.delete(key);
  }
}

/**
 * Record an attempt against `key`. Returns whether it is allowed.
 *
 * @param limit   attempts permitted per window
 * @param windowMs length of the fixed window
 */
export function hit(key: string, limit: number, windowMs: number): RateLimitResult {
  const now = Date.now();
  sweep(now);

  const existing = buckets.get(key);
  if (!existing || existing.resetAt <= now) {
    buckets.set(key, { count: 1, resetAt: now + windowMs });
    return { allowed: true, retryAfterSeconds: 0 };
  }

  existing.count += 1;
  if (existing.count > limit) {
    return {
      allowed: false,
      retryAfterSeconds: Math.max(1, Math.ceil((existing.resetAt - now) / 1000)),
    };
  }
  return { allowed: true, retryAfterSeconds: 0 };
}

/** Drop a key's window — call after a successful login so one bad typo doesn't linger. */
export function reset(key: string): void {
  buckets.delete(key);
}

/** Test seam. */
export function clearAll(): void {
  buckets.clear();
}
