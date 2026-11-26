/**
 * Per-visitor limits on the query-driven research pages (audit RS-6).
 *
 * The API no longer limits the web server's own calls (`lib/web-server-key.ts`),
 * so each visitor is counted here, by their address, in the same Postgres
 * fixed-window counters the sign-in throttle uses (`lib/rate-limit.ts`). The
 * limits match what the API applied to one client before: 30 screener or
 * compare views a minute, 60 stock pages.
 *
 * The address is the `X-Forwarded-For` entry our own proxy added
 * (`lib/client-address.ts`, `TRUSTED_PROXY_HOPS` from the right), never the
 * client-chosen left-most one. Railway's edge also replaces any client value
 * (probed 11 Nov 2026, workspace `docs/rate-limit-keys-note.md`). Raise
 * `TRUSTED_PROXY_HOPS` if another proxy or CDN is put in front.
 *
 * A counter that cannot be written does not block the page: these limits
 * protect capacity, not accounts, so they fail open (sign-in fails closed).
 */

import "server-only";

import { headers } from "next/headers";

import { clientAddress } from "@/lib/client-address";
import { type RateLimitResult, hit } from "@/lib/rate-limit";

export const VISITOR_LIMITS = {
  screener: 30,
  compare: 30,
  reactions: 20,
  stock: 60,
  // A4.1: rule strategy runs, signed out (the API's own limit is 20 a minute).
  strategy: 20,
  // A4.5: scan event studies, signed out (the API allows 10 a minute).
  eventStudy: 10,
  // News redesign: the archive page runs two queries a view.
  news: 60,
} as const;

export type VisitorScope = keyof typeof VISITOR_LIMITS;

const WINDOW_MS = 60_000;

export function visitorAddress(h: Pick<Headers, "get">): string {
  return clientAddress(h);
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
