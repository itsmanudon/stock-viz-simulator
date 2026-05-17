import { apiGet } from "./client";
import type { ScreenerResult } from "./types";

export type ScreenParams = {
  sector?: string;
  rsiMin?: number;
  rsiMax?: number;
  momentumDays?: number;
  momentumMin?: number;
  momentumMax?: number;
  near52wHigh?: boolean;
  near52wLow?: boolean;
};

export function screenSymbols(params: ScreenParams = {}): Promise<ScreenerResult[]> {
  const q = new URLSearchParams();
  if (params.sector) q.set("sector", params.sector);
  if (params.rsiMin !== undefined) q.set("rsi_min", String(params.rsiMin));
  if (params.rsiMax !== undefined) q.set("rsi_max", String(params.rsiMax));
  if (params.momentumDays !== undefined) q.set("momentum_days", String(params.momentumDays));
  if (params.momentumMin !== undefined) q.set("momentum_min", String(params.momentumMin));
  if (params.momentumMax !== undefined) q.set("momentum_max", String(params.momentumMax));
  if (params.near52wHigh) q.set("near_52w_high", "true");
  if (params.near52wLow) q.set("near_52w_low", "true");
  const qs = q.toString();
  return apiGet<ScreenerResult[]>(`/v1/symbols/screen${qs ? `?${qs}` : ""}`);
}
