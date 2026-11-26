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

export type Forensics = components["schemas"]["ForensicsOut"];

/** A7.3 (M5.1, M5.2): Piotroski, Altman Z'' and Beneish on the latest known fiscal years. */
export function getForensics(ticker: string): Promise<Forensics> {
  return apiGet<Forensics>(`/v1/symbols/${encodeURIComponent(ticker)}/forensics`, CACHE);
}

export type ReverseDcf = components["schemas"]["ReverseDcfOut"];

/** A7.4 (M5.3): the growth the price implies, at the default inputs. */
export function getReverseDcf(ticker: string): Promise<ReverseDcf> {
  return apiGet<ReverseDcf>(`/v1/symbols/${encodeURIComponent(ticker)}/reverse-dcf`, CACHE);
}
