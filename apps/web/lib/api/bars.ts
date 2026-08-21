import { apiGet } from "./client";
import type { Bar } from "./types";

export type BarsParams = {
  interval?: "1d" | "1h";
  from?: string;
  to?: string;
  limit?: number;
};

export function getBars(ticker: string, params: BarsParams = {}): Promise<Bar[]> {
  const q = new URLSearchParams();
  if (params.interval) q.set("interval", params.interval);
  if (params.from) q.set("from", params.from);
  if (params.to) q.set("to", params.to);
  if (params.limit) q.set("limit", String(params.limit));
  const qs = q.toString();
  // EOD bars change once a day; caching keeps chart pages responsive while the
  // free-tier API cold-starts. `revalidateTag("bars")` busts them.
  return apiGet<Bar[]>(`/v1/symbols/${encodeURIComponent(ticker)}/bars${qs ? `?${qs}` : ""}`, {
    revalidateSeconds: 3600,
    tags: ["bars"],
  });
}
