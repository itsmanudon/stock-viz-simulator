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
  greeks: OptionGreeks;
  /** How `volatility` was estimated, in words (Phase 9.1). */
  volatility_method: string;
  volatility_closes: number;
  /** True when the model price was under the 0.01-a-share minimum (LG-14). */
  premium_floor_applied: boolean;
  side: "long" | "short";
  risk: OptionRisk;
};

/**
 * What the position can lose and must hold back (Phase 9.2), in USD.
 * `collateral` is cash reserved (a cash-secured put's strike value);
 * `shares_reserved` the shares a covered call holds back. `max_gain` is null
 * when unbounded.
 */
export type OptionRisk = {
  collateral: string;
  shares_reserved: string;
  max_loss: string;
  max_gain: string | null;
  breakeven: string;
  basis: string;
};

/**
 * Per-share Black-Scholes Greeks. `theta` is per calendar day; `vega` and
 * `rho` are per 1.00 (100 points) of volatility and of the rate.
 */
export type OptionGreeks = {
  delta: number;
  gamma: number;
  theta: number;
  vega: number;
  rho: number;
};

export type ImpliedVolatility = {
  ticker: string;
  strike: string;
  expiry: string;
  per_share_price: string;
  /** Annualised (0.25 = 25%), or null with `reason`. */
  implied_volatility: number | null;
  reason: string | null;
  /** The volatility StockViz prices with, for comparison. */
  historical_volatility: number;
};

export type OptionQuoteRequest = {
  ticker: string;
  option_type: "call" | "put";
  /** Omit to price at the money. */
  strike?: string;
  expiry: string;
  quantity: number;
  /** Long buys to open; short writes a covered contract. Default long. */
  side?: "long" | "short";
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
  if (request.side) params.set("side", request.side);
  return apiGet<OptionQuote>(`/v1/options/quote?${params}`, {
    init: { signal },
    maxAttempts: 1,
  });
}

/** GET /v1/options/implied-volatility: the volatility a per-share price implies. */
export function getImpliedVolatility(
  request: Omit<OptionQuoteRequest, "quantity" | "strike" | "side"> & {
    strike: string;
    price: string;
  },
  signal?: AbortSignal,
): Promise<ImpliedVolatility> {
  const params = new URLSearchParams({
    ticker: request.ticker,
    option_type: request.option_type,
    expiry: request.expiry,
    strike: request.strike,
    price: request.price,
  });
  return apiGet<ImpliedVolatility>(`/v1/options/implied-volatility?${params}`, {
    init: { signal },
    maxAttempts: 1,
  });
}
