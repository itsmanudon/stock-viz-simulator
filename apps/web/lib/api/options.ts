import "server-only";

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

export function tradeOption(body: OpenOptionInput | CloseOptionInput): Promise<OptionTradeResult> {
  return authedPost<OptionTradeResult>("/v1/options/trade", body);
}
