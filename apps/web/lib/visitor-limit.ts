/**
 * Per-visitor limits on the query-driven research pages (audit RS-6).
 *
 * The API no longer limits the web server's own calls (`lib/web-server-key.ts`),
 * so each visitor is counted here, by their address, in the same Postgres
 * fixed-window counters the sign-in throttle uses (`lib/rate-limit.ts`). The
 * limits match what the API applied to one client before: 30 screener or
 * compare views a minute, 60 stock pages.
 *
 * The address is the left-most `X-Forwarded-For` entry. Railway's edge
 * replaces any client-supplied value (probed 11 Nov 2026, see the workspace
 * `docs/rate-limit-keys-note.md`), so a visitor cannot pick their own key.
 * Re-check that if another proxy or CDN is put in front.
 *
 * A counter that cannot be written does not block the page: these limits
 * protect capacity, not accounts, so they fail open (sign-in fails closed).
 */

import "server-only";

import { headers } from "next/headers";

import { type RateLimitResult, hit } from "@/lib/rate-limit";

export const VISITOR_LIMITS = {
  screener: 30,
  compare: 30,
  reactions: 20,
  stock: 60,
} as const;

export type VisitorScope = keyof typeof VISITOR_LIMITS;

const WINDOW_MS = 60_000;

export function visitorAddress(h: Pick<Headers, "get">): string {
  const forwarded = h.get("x-forwarded-for")?.split(",")[0]?.trim();
  if (forwarded) return forwarded;
  return h.get("x-real-ip")?.trim() || "unknown";
}

export async function checkVisitorLimit(scope: VisitorScope): Promise<RateLimitResult> {
  const address = visitorAddress(await headers());
  try {
    return await hit(`visitor:${scope}:${address}`, VISITOR_LIMITS[scope], WINDOW_MS);
  } catch (err) {
    console.error(`visitor limit unavailable for ${scope}`, err);
    return { allowed: true, retryAfterSeconds: 0 };
  }
}
