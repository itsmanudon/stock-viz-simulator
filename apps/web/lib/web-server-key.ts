/**
 * The key the web server sends on its server-side API calls (audit RS-6).
 *
 * The web server reaches the API over Railway's private network with no
 * forwarded address, so the API's limiter put every visitor of every
 * server-rendered page in one bucket. The API now skips its public limiter
 * for requests carrying `X-StockViz-Web`: an HMAC-SHA256 of a fixed label
 * under `INTERNAL_API_TOKEN`, which both services hold
 * (`apps/api/src/stockviz/limiter.py`). Visitors are limited here instead,
 * by their own address (`lib/visitor-limit.ts`).
 *
 * `lib/api/client.ts` is shared with the browser bundle, so it cannot import
 * this module. `instrumentation.ts` registers the key on the server at start
 * up and the client reads it from `globalThis`; in the browser it is never
 * set. The value never changes, so it does not split Next's fetch cache.
 */

import "server-only";

import { createHmac } from "node:crypto";

import { requireSecret } from "@/lib/env";

export const WEB_SERVER_HEADER = "X-StockViz-Web";
const LABEL = "stockviz-web-server-rate-limit-v1";
export const WEB_SERVER_KEY_SLOT = Symbol.for("stockviz.webServerKey");

export function webServerKey(secret: string): string {
  return createHmac("sha256", secret).update(LABEL).digest("hex");
}

/** Store the key where `lib/api/client.ts` finds it. Server only. */
export function registerWebServerKey(): void {
  (globalThis as Record<symbol, unknown>)[WEB_SERVER_KEY_SLOT] = webServerKey(
    requireSecret("INTERNAL_API_TOKEN"),
  );
}
