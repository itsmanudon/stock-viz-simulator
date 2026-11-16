/**
 * Option strategies (Phase 9.3 to 9.5), the browser-safe part: the template
 * list and `POST /v1/options/strategies/payoff`, a public call that prices
 * every leg and returns the payoff curves. Opening and closing are per-user
 * and go through server actions (`lib/api/options.ts`).
 */

import { apiPost } from "./client";

export type StrategyKind =
  | "covered_call"
  | "cash_secured_put"
  | "protective_put"
  | "bull_call"
  | "bear_put"
  | "bull_put"
  | "bear_call"
  | "iron_condor"
  | "straddle"
  | "strangle"
  | "calendar";

export type StrategyTemplate = {
  kind: StrategyKind;
  label: string;
  /** Strike inputs, low to high, with what each one is. */
  strikes: string[];
  summary: string;
};

/** Every template, in the order the builder lists them. */
export const STRATEGY_TEMPLATES: StrategyTemplate[] = [
  {
    kind: "covered_call",
    label: "Covered call",
    strikes: ["Call strike"],
    summary: "Write a call on shares you hold: earn the premium, give up gains above the strike.",
  },
  {
    kind: "cash_secured_put",
    label: "Cash-secured put",
    strikes: ["Put strike"],
    summary:
      "Write a put with its strike value held in cash: earn the premium, or buy at the strike.",
  },
  {
    kind: "protective_put",
    label: "Protective put",
    strikes: ["Put strike"],
    summary: "Buy a put on shares you hold: losses below the strike are covered.",
  },
  {
    kind: "bull_call",
    label: "Bull call spread",
    strikes: ["Buy call", "Write call"],
    summary: "A debit spread that gains as the stock rises, up to the higher strike.",
  },
  {
    kind: "bear_put",
    label: "Bear put spread",
    strikes: ["Write put", "Buy put"],
    summary: "A debit spread that gains as the stock falls, down to the lower strike.",
  },
  {
    kind: "bull_put",
    label: "Bull put spread",
    strikes: ["Buy put", "Write put"],
    summary: "A credit spread that keeps the premium if the stock stays above the higher strike.",
  },
  {
    kind: "bear_call",
    label: "Bear call spread",
    strikes: ["Write call", "Buy call"],
    summary: "A credit spread that keeps the premium if the stock stays below the lower strike.",
  },
  {
    kind: "iron_condor",
    label: "Iron condor",
    strikes: ["Buy put", "Write put", "Write call", "Buy call"],
    summary:
      "Two credit spreads: keeps the premium while the stock stays between the inner strikes.",
  },
  {
    kind: "straddle",
    label: "Straddle",
    strikes: ["Strike"],
    summary: "Buy a call and a put at one strike: gains on a large move either way.",
  },
  {
    kind: "strangle",
    label: "Strangle",
    strikes: ["Buy put", "Buy call"],
    summary: "Buy a put and a call at two strikes: cheaper than a straddle, needs a larger move.",
  },
  {
    kind: "calendar",
    label: "Calendar spread",
    strikes: ["Strike"],
    summary:
      "Write a near expiry and buy a far one at the same strike: gains if the stock sits near it.",
  },
];

export type StrategyRequest = {
  kind: StrategyKind;
  ticker: string;
  strikes: string[];
  expiry: string;
  far_expiry?: string;
  option_type?: "call" | "put";
  quantity: number;
};

export type StrategyLegQuote = {
  side: "long" | "short";
  option_type: "call" | "put";
  strike: string;
  expiry: string;
  per_share: string;
  premium: string;
};

export type StrategyRisk = {
  /** Positive when the open credits cash. */
  net_premium: string;
  collateral: string;
  shares_reserved: string;
  max_loss: string;
  max_gain: string | null;
  breakevens: string[];
  basis: string;
};

export type StrategyQuote = {
  kind: StrategyKind;
  label: string;
  ticker: string;
  quantity: number;
  spot: string;
  spot_at: string;
  legs: StrategyLegQuote[];
  risk: StrategyRisk;
};

export type PayoffPoint = { spot: number; at_expiry: number; today: number };

export type StrategyPayoff = {
  quote: StrategyQuote;
  horizon: string;
  points: PayoffPoint[];
  /** Model chance of profit at the first expiry (0 to 1), or null. */
  prob_profit: number | null;
  volatility: number;
  method: string;
};

export function getStrategyPayoff(
  request: StrategyRequest,
  signal?: AbortSignal,
): Promise<StrategyPayoff> {
  return apiPost<StrategyPayoff>("/v1/options/strategies/payoff", request, {
    init: { signal },
    maxAttempts: 1,
  });
}

/** Strike step for a price: 1 under 50, 5 under 250, else 10. */
export function strikeStep(spot: number): number {
  if (spot < 50) return 1;
  if (spot < 250) return 5;
  return 10;
}

/** Default strikes around today's close for a template (low to high). */
export function defaultStrikes(kind: StrategyKind, spot: number): string[] {
  const s = strikeStep(spot);
  const atm = Math.max(s, Math.round(spot / s) * s);
  const at = (n: number) => String(Math.max(s, atm + n * s));
  switch (kind) {
    case "covered_call":
      return [at(1)];
    case "cash_secured_put":
    case "protective_put":
      return [at(-1)];
    case "bull_call":
    case "bear_call":
      return [at(0), at(2)];
    case "bear_put":
    case "bull_put":
      return [at(-2), at(0)];
    case "iron_condor":
      return [at(-3), at(-1), at(1), at(3)];
    case "strangle":
      return [at(-1), at(1)];
    default:
      return [at(0)];
  }
}
