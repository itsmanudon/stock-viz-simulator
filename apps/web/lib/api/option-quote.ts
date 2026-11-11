/**
 * GET /v1/options/quote: what opening a contract would cost now (audit LG-7).
 * Public and browser-safe; the server prices it with the function the open
 * charges with, so the preview is the premium the buy takes.
 */

import { apiGet } from "./client";

export type OptionQuote = {
  ticker: string;
  option_type: "call" | "put";
  /** The strike priced: the one asked for, or at the money when none was. */
  strike: string;
  expiry: string;
  quantity: number;
  /** Latest stored close and its bar timestamp (UTC, no zone). */
  spot: string;
  spot_at: string;
  /** Annualised 30-day historical volatility, the IV proxy (0.25 = 25%). */
  volatility: number;
  risk_free_rate: number;
  per_share: string;
  /** USD charge for `quantity` contracts of `contract_size` shares. */
  premium: string;
  contract_size: number;
  greeks: { delta: number; gamma: number; theta: number; vega: number };
};

export type OptionQuoteRequest = {
  ticker: string;
  option_type: "call" | "put";
  /** Omit to price at the money. */
  strike?: string;
  expiry: string;
  quantity: number;
};

export function getOptionQuote(
  request: OptionQuoteRequest,
  signal?: AbortSignal,
): Promise<OptionQuote> {
  const params = new URLSearchParams({
    ticker: request.ticker,
    option_type: request.option_type,
    expiry: request.expiry,
    quantity: String(request.quantity),
  });
  if (request.strike) params.set("strike", request.strike);
  return apiGet<OptionQuote>(`/v1/options/quote?${params}`, {
    init: { signal },
    maxAttempts: 1,
  });
}
