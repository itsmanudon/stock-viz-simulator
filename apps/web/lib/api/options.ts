import "server-only";

import { withBook } from "./books";
import type { StrategyKind, StrategyRequest } from "./option-strategies";
import { authedGet, authedPost } from "./server";

export type { OptionGreeks } from "./option-quote";
import type { OptionGreeks } from "./option-quote";

export type OptionPosition = {
  id: number;
  ticker: string;
  option_type: "call" | "put";
  strike: string;
  expiry: string;
  quantity: number;
  premium_paid: string;
  status: "open" | "closed" | "exercised" | "expired";
  opened_at: string;
  current_value: string;
  greeks: OptionGreeks;
  /** Phase 9.2: a short leg's premium_paid is the premium it received. */
  side?: OptionSide;
  cover?: "shares" | "cash" | "leg" | null;
  strategy_id?: number | null;
  covering_leg_id?: number | null;
  collateral?: string;
  shares_reserved?: string;
};

/** Long: bought to open. Short: written to open, always covered (Phase 9.2). */
export type OptionSide = "long" | "short";

export type OptionTradeResult = {
  position: OptionPosition;
  cash_delta: string;
};

export type OpenOptionInput = {
  action: "open";
  ticker: string;
  option_type: "call" | "put";
  strike: string;
  expiry: string;
  quantity: number;
  /** "short" writes a covered call or a cash-secured put (Phase 9.2). */
  side?: OptionSide;
  /** A repeat with the same key returns the first contract (audit LG-10). */
  client_order_id?: string;
};

export type CloseOptionInput = {
  action: "close";
  option_id: number;
};

export function listOptionsPositions(): Promise<OptionPosition[]> {
  return authedGet<OptionPosition[]>("/v1/options/positions");
}

export function tradeOption(
  body: OpenOptionInput | CloseOptionInput,
  book?: number | null,
): Promise<OptionTradeResult> {
  return authedPost<OptionTradeResult>(withBook("/v1/options/trade", book), body);
}

// ---------------------------------------------------------------------------
// Strategies and the book (Phase 9.3 to 9.5)
// ---------------------------------------------------------------------------

export type OptionStrategy = {
  id: number;
  kind: StrategyKind;
  label: string;
  status: "open" | "closed" | "settled";
  /** Positive when the open credited cash. */
  net_premium: string;
  collateral: string;
  max_loss: string | null;
  max_gain: string | null;
  opened_at: string;
  legs: OptionPosition[];
};

export type OptionStrategyTrade = { strategy: OptionStrategy; cash_delta: string };

export type UnderlyingGreeks = {
  ticker: string;
  spot: string;
  delta_shares: number;
  dollar_delta: number;
  gamma_shares: number;
  theta_per_day: number;
  vega_per_point: number;
  rho_per_point: number;
};

export type ExpiryItem = {
  label: string;
  legs: string[];
  at_risk: string | null;
  outcome: string;
  net_cash: string | null;
  strategy_id: number | null;
};

export type OptionsBook = {
  underlyings: UnderlyingGreeks[];
  dollar_delta: number;
  theta_per_day: number;
  vega_per_point: number;
  rho_per_point: number;
  expirations: { expiry: string; items: ExpiryItem[] }[];
  unpriced: string[];
  method: string;
};

export function openStrategy(
  body: StrategyRequest & { client_order_id?: string },
  book?: number | null,
): Promise<OptionStrategyTrade> {
  return authedPost<OptionStrategyTrade>(withBook("/v1/options/strategies", book), body);
}

export function listStrategies(book?: number | null): Promise<OptionStrategy[]> {
  return authedGet<OptionStrategy[]>(withBook("/v1/options/strategies", book));
}

export function closeStrategy(id: number): Promise<OptionStrategyTrade> {
  return authedPost<OptionStrategyTrade>(`/v1/options/strategies/${id}/close`, {});
}

export function getOptionsBook(book?: number | null): Promise<OptionsBook> {
  return authedGet<OptionsBook>(withBook("/v1/options/book", book));
}
