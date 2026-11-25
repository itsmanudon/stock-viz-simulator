/**
 * A3.5 public reads beside the stock chart: chart events (news, earnings,
 * dividends, splits), relative strength, delivery % and the market regime.
 * Cached an hour with the bars (tag `bars`), so the nightly revalidate drops
 * them together. Fills are per user: `lib/api/events-server.ts`.
 */

import type { SymbolEvents } from "@/lib/chart-events";

import { apiGet } from "./client";
import type { components } from "./schema";

export type RelativeStrength = components["schemas"]["RelativeStrengthOut"];
export type Delivery = components["schemas"]["DeliveryOut"];
export type DeliveryPoint = components["schemas"]["DeliveryPointOut"];
export type Regime = components["schemas"]["RegimeOut"];
export type MarketRegime = components["schemas"]["MarketRegimeOut"];

export function getSymbolEvents(
  ticker: string,
  range: { from: string; to: string },
  types = "news,earnings,dividend,split",
): Promise<SymbolEvents> {
  const q = new URLSearchParams({ from: range.from, to: range.to, types });
  return apiGet<SymbolEvents>(`/v1/symbols/${encodeURIComponent(ticker)}/events?${q}`, {
    revalidateSeconds: 3600,
    tags: ["bars", "news"],
  });
}

export function getRelativeStrength(ticker: string): Promise<RelativeStrength> {
  return apiGet<RelativeStrength>(`/v1/symbols/${encodeURIComponent(ticker)}/relative-strength`, {
    revalidateSeconds: 3600,
    tags: ["bars"],
  });
}

export function getDelivery(
  ticker: string,
  interval: "1d" | "1wk" | "1mo",
  from?: string,
): Promise<Delivery> {
  const q = new URLSearchParams({ interval });
  if (from) q.set("from", from);
  return apiGet<Delivery>(`/v1/symbols/${encodeURIComponent(ticker)}/delivery?${q}`, {
    revalidateSeconds: 3600,
    tags: ["bars"],
  });
}

export function getRegime(): Promise<Regime> {
  return apiGet<Regime>("/v1/regime", { revalidateSeconds: 600, tags: ["bars"] });
}
