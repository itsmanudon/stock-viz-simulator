import { apiGet } from "./client";
import type { Quote } from "./types";

export function getQuotes(tickers: string[]): Promise<Quote[]> {
  if (tickers.length === 0) return Promise.resolve([]);
  const qs = new URLSearchParams({ tickers: tickers.join(",") }).toString();
  return apiGet<Quote[]>(`/v1/quotes?${qs}`);
}
