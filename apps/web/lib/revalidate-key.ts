/**
 * The key the nightly cron sends to `POST /api/revalidate` (audit RS-9,
 * Phase 6.6): an HMAC-SHA256 of a fixed label under `INTERNAL_API_TOKEN`,
 * which the API's cron and the web both hold. The API side is
 * `stockviz.cli revalidate_key`.
 */

import "server-only";

import { createHmac, timingSafeEqual } from "node:crypto";

export const REVALIDATE_HEADER = "x-stockviz-revalidate";
const LABEL = "stockviz-revalidate-v1";

export function revalidateKey(secret: string): string {
  return createHmac("sha256", secret).update(LABEL).digest("hex");
}

export function isValidRevalidateKey(supplied: string | null, secret: string): boolean {
  if (!supplied) return false;
  const expected = Buffer.from(revalidateKey(secret));
  const given = Buffer.from(supplied);
  return given.length === expected.length && timingSafeEqual(given, expected);
}

/** Every tag whose data the nightly run rewrites. */
export const MARKET_TAGS = [
  "bars",
  "markets",
  "symbols",
  "screener",
  "fundamentals",
  "recommendations",
  "news",
] as const;
