import "server-only";

import { authedGet, authedPost } from "./server";

export type OptionGreeks = {
  delta: number;
  gamma: number;
  theta: number;
  vega: number;
};

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
};

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
