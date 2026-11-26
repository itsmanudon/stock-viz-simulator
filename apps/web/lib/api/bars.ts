import { apiGet } from "./client";
import type { ApiInterval, Bar } from "./types";

export type BarsParams = {
  /** A1.4a: weekly and monthly bars are resampled from the daily ones. */
  interval?: ApiInterval;
  from?: string;
  to?: string;
  limit?: number;
  /** A3.1: `raw` reads the exchange's own numbers (409 when none are stored). */
  adjustment?: "adjusted" | "raw";
};

const INTRADAY = new Set(["1m", "5m", "15m", "30m", "60m"]);

export function getBars(ticker: string, params: BarsParams = {}): Promise<Bar[]> {
  const q = new URLSearchParams();
  if (params.interval) q.set("interval", params.interval);
  if (params.from) q.set("from", params.from);
  if (params.to) q.set("to", params.to);
  if (params.limit) q.set("limit", String(params.limit));
  if (params.adjustment && params.adjustment !== "adjusted") q.set("adjustment", params.adjustment);
  const qs = q.toString();
  // EOD bars change once a day; caching keeps chart pages responsive while the
  // free-tier API cold-starts. `revalidateTag("bars")` busts them.
  return apiGet<Bar[]>(`/v1/symbols/${encodeURIComponent(ticker)}/bars${qs ? `?${qs}` : ""}`, {
    // A6.2: intraday bars can change within the hour (a live feed later).
    revalidateSeconds: INTRADAY.has(params.interval ?? "1d") ? 60 : 3600,
    tags: ["bars"],
  });
}
