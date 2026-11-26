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

export type Forecast = components["schemas"]["ForecastOut"];

/** A9.2: HAR-RV against a random walk, and conformal cones with realised coverage. */
export function getForecast(ticker: string): Promise<Forecast> {
  return apiGet<Forecast>(`/v1/symbols/${encodeURIComponent(ticker)}/forecast`, CACHE);
}

export type Pair = components["schemas"]["PairOut"];

/** A9.3: Engle-Granger cointegration of two stored symbols. */
export function getPair(a: string, b: string, years = 3): Promise<Pair> {
  return apiGet<Pair>(
    `/v1/symbols/${encodeURIComponent(a)}/pair/${encodeURIComponent(b)}?years=${years}`,
    CACHE,
  );
}
