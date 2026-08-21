import { apiGet } from "./client";
import type { SymbolDetail, Symbol as SymbolRow } from "./types";

export type ListSymbolsParams = {
  sector?: string;
  exchange?: string;
  activeOnly?: boolean;
};

export function listSymbols(params: ListSymbolsParams = {}): Promise<SymbolRow[]> {
  const q = new URLSearchParams();
  if (params.sector) q.set("sector", params.sector);
  if (params.exchange) q.set("exchange", params.exchange);
  if (params.activeOnly === false) q.set("active_only", "false");
  const qs = q.toString();
  // The symbol universe changes when a seed/metadata job runs, not per request.
  return apiGet<SymbolRow[]>(`/v1/symbols${qs ? `?${qs}` : ""}`, {
    revalidateSeconds: 3600,
    tags: ["symbols"],
  });
}

export function getSymbol(ticker: string): Promise<SymbolDetail> {
  return apiGet<SymbolDetail>(`/v1/symbols/${encodeURIComponent(ticker)}`);
}

/**
 * Typeahead over ticker and company name.
 *
 * Not cached: the query changes with every keystroke, so a cache entry would
 * never be reused and would only add storage churn.
 */
export function searchSymbols(q: string, limit = 10): Promise<SymbolRow[]> {
  const query = q.trim();
  if (!query) return Promise.resolve([]);
  return apiGet<SymbolRow[]>(
    `/v1/symbols/search?q=${encodeURIComponent(query)}&limit=${limit}`,
    // One attempt: the user is typing and will retry by keeping going.
    { maxAttempts: 1 },
  );
}
