/** A7.9 (M6.2): GEX/DEX and key levels from the newest stored US chain. */

import { apiGet } from "./client";
import type { components } from "./schema";

export type OptionExposure = components["schemas"]["OptionExposureOut"];

export function getOptionExposure(ticker: string): Promise<OptionExposure> {
  return apiGet<OptionExposure>(`/v1/options/${encodeURIComponent(ticker)}/exposure`, {
    revalidateSeconds: 3600,
    tags: ["options"],
  });
}

export type VolSummary = components["schemas"]["VolSummaryOut"];

/** A9.4 (M6.3): term structure, 25-delta skew, VRP and IV rank from stored chains. */
export function getVolSummary(ticker: string): Promise<VolSummary> {
  return apiGet<VolSummary>(`/v1/options/${encodeURIComponent(ticker)}/vol-summary`, {
    revalidateSeconds: 3600,
    tags: ["options"],
  });
}
