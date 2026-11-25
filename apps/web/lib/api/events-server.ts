import "server-only";

/**
 * A3.5: the signed-in viewer's own fills on a symbol, for the chart's fill
 * markers. Authed (`/v1/symbols/{t}/events?types=fill` with the server's
 * Bearer token), never cached, never from the browser: the API returns only
 * the token's user's trades.
 */

import type { FillEvent, SymbolEvents } from "@/lib/chart-events";

import { authedGet } from "./server";

export async function getMyFills(
  ticker: string,
  range: { from: string; to: string },
): Promise<FillEvent[]> {
  const q = new URLSearchParams({ from: range.from, to: range.to, types: "fill" });
  const body = await authedGet<SymbolEvents>(
    `/v1/symbols/${encodeURIComponent(ticker)}/events?${q}`,
  );
  return body.events.filter((e): e is FillEvent => e.type === "fill");
}
