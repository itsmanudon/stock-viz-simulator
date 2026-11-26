/** A9 research views on stored data: seasonality and the post-earnings drift. */

import { apiGet } from "./client";
import type { components } from "./schema";

export type Seasonality = components["schemas"]["SeasonalityOut"];
export type EarningsDrift = components["schemas"]["EarningsDriftOut"];

const CACHE = { revalidateSeconds: 3600, tags: ["bars"] };

export function getSeasonality(ticker: string): Promise<Seasonality> {
  return apiGet<Seasonality>(`/v1/symbols/${encodeURIComponent(ticker)}/seasonality`, CACHE);
}

export function getEarningsDrift(ticker: string): Promise<EarningsDrift> {
  return apiGet<EarningsDrift>(`/v1/symbols/${encodeURIComponent(ticker)}/earnings-drift`, CACHE);
}
