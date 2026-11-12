import { apiGet } from "./client";
import type { components } from "./schema";

export type Fundamentals = components["schemas"]["FundamentalsOut"];
export type Valuation = components["schemas"]["ValuationOut"];
export type ValuationHistory = components["schemas"]["ValuationHistoryOut"];

/** Statement figures and multiples change weekly at most (Phase 6.3-6.4). */
const CACHE = { revalidateSeconds: 3600, tags: ["fundamentals"] };

export function getFundamentals(
  ticker: string,
  period: "annual" | "quarter",
): Promise<Fundamentals> {
  return apiGet<Fundamentals>(
    `/v1/symbols/${encodeURIComponent(ticker)}/fundamentals?period=${period}&periods=5`,
    CACHE,
  );
}

export function getValuation(ticker: string): Promise<Valuation> {
  return apiGet<Valuation>(`/v1/symbols/${encodeURIComponent(ticker)}/valuation`, CACHE);
}

export function getValuationHistory(ticker: string, metric = "pe"): Promise<ValuationHistory> {
  return apiGet<ValuationHistory>(
    `/v1/symbols/${encodeURIComponent(ticker)}/valuation/history?metric=${metric}&years=5`,
    CACHE,
  );
}
