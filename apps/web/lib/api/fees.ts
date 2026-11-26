/**
 * A4.2: fee schedules and the order review's fee estimate. Both public.
 * `getFeeEstimate` is a browser call (like the option quote); the schedules
 * are read by the /docs/costs page on the server.
 */

import type { FeeEstimate, FeeSchedules } from "../fees";
import { apiGet } from "./client";

export function getFeeSchedules(): Promise<FeeSchedules> {
  return apiGet<FeeSchedules>("/v1/fees/schedules", { revalidateSeconds: 3600 });
}

export function getFeeEstimate(
  request: { ticker: string; side: "buy" | "sell"; quantity: string; price?: string | null },
  signal?: AbortSignal,
): Promise<FeeEstimate> {
  const params = new URLSearchParams({
    ticker: request.ticker,
    side: request.side,
    quantity: request.quantity,
  });
  if (request.price) params.set("price", request.price);
  return apiGet<FeeEstimate>(`/v1/fees/estimate?${params}`, {
    init: { signal },
    maxAttempts: 1,
  });
}
