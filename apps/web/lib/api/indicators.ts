import { apiGet } from "./client";
import type { Indicators } from "./types";

export type IndicatorsParams = {
  names: string[];
  interval?: "1d" | "1h";
  from?: string;
  to?: string;
  limit?: number;
};

export function getIndicators(ticker: string, params: IndicatorsParams): Promise<Indicators> {
  const q = new URLSearchParams({ names: params.names.join(",") });
  if (params.interval) q.set("interval", params.interval);
  if (params.from) q.set("from", params.from);
  if (params.to) q.set("to", params.to);
  if (params.limit) q.set("limit", String(params.limit));
  // Cached with the bars they are drawn on (RS-9); refreshed together nightly.
  return apiGet<Indicators>(
    `/v1/symbols/${encodeURIComponent(ticker)}/indicators?${q.toString()}`,
    { revalidateSeconds: 3600, tags: ["bars"] },
  );
}
