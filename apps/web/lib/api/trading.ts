import "server-only";

import { authedGet, authedPost } from "./server";

export type Position = {
  ticker: string;
  name: string;
  quantity: string;
  avg_cost: string;
  last_close: string | null;
  market_value: string;
  unrealized_pl: string;
};

export type Portfolio = {
  portfolio_id: number;
  cash_balance: string;
  market_value: string;
  total_value: string;
  total_cost_basis: string;
  unrealized_pl: string;
  positions: Position[];
};

export type TradeRow = {
  id: number;
  ticker: string;
  side: "buy" | "sell";
  quantity: string;
  price: string;
  ts: string;
};

export type TradeInput = {
  ticker: string;
  side: "buy" | "sell";
  quantity: string;
};

export function getPortfolio(): Promise<Portfolio> {
  return authedGet<Portfolio>("/v1/portfolio");
}

export function postTrade(body: TradeInput): Promise<TradeRow> {
  return authedPost<TradeRow>("/v1/trades", body);
}

export function listTrades(limit = 100): Promise<TradeRow[]> {
  return authedGet<TradeRow[]>(`/v1/trades?limit=${limit}`);
}
