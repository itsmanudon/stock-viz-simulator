import { apiGet } from "./client";
import type { MarketsSummary } from "./types";

export type MarketsSummaryParams = {
  sector?: string;
  /** Number of closes to include in each row's sparkline series. */
  sparklineDays?: number;
};

/**
 * Everything the /markets table needs, in one request.
 *
 * Replaces the previous shape — two `listSymbols` calls plus one `getBars` per
 * symbol — which issued 34 backend requests for a 32-symbol universe and grew
 * linearly from there.
 *
 * EOD bars change once a day, so this is cached for an hour rather than
 * `no-store`; it also keeps the page responsive while the API cold-starts.
 */
export function getMarketsSummary(params: MarketsSummaryParams = {}): Promise<MarketsSummary> {
  const q = new URLSearchParams();
  if (params.sector) q.set("sector", params.sector);
  if (params.sparklineDays) q.set("sparkline_days", String(params.sparklineDays));
  const qs = q.toString();
  return apiGet<MarketsSummary>(`/v1/markets/summary${qs ? `?${qs}` : ""}`, {
    revalidateSeconds: 3600,
    tags: ["markets", "bars"],
  });
}
