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
  return apiGet<SymbolRow[]>(`/v1/symbols${qs ? `?${qs}` : ""}`);
}

export function getSymbol(ticker: string): Promise<SymbolDetail> {
  return apiGet<SymbolDetail>(`/v1/symbols/${encodeURIComponent(ticker)}`);
}
