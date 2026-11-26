/**
 * GET /v1/symbols/{ticker}/avwap (A3.3): an anchored VWAP from a daily anchor
 * date, on daily bars or sampled at each weekly/monthly bar's time (it is
 * always computed from daily bars). Public; the chart asks for it through
 * `app/(product)/stocks/[ticker]/avwap-actions.ts`.
 */

import { apiGet } from "./client";
import type { components } from "./schema";

export type Avwap = components["schemas"]["AvwapOut"];
export type AvwapPoint = components["schemas"]["AvwapPointOut"];

export function getAvwap(
  ticker: string,
  anchor: string,
  interval: "1d" | "1wk" | "1mo",
  bands: number,
): Promise<Avwap> {
  const q = new URLSearchParams({ anchor, interval, bands: String(bands) });
  return apiGet<Avwap>(`/v1/symbols/${encodeURIComponent(ticker)}/avwap?${q.toString()}`, {
    maxAttempts: 1,
  });
}
