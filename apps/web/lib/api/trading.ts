import "server-only";

import { authedDelete, authedGet, authedPost } from "./server";

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

export type PortfolioHistoryPoint = {
  date: string;
  nav: string;
};

export function getPortfolioHistory(days: number | null = 90): Promise<PortfolioHistoryPoint[]> {
  const qs = days === null ? "" : `?days=${days}`;
  return authedGet<PortfolioHistoryPoint[]>(`/v1/portfolio/history${qs}`);
}

export type DividendCredit = {
  ticker: string;
  ex_date: string;
  amount_credited: string;
  credited_at: string;
};

export type ProjectedDividend = {
  ticker: string;
  projected_ex_date: string | null;
  projected_amount: string;
};

export type DividendSummary = {
  ytd_income: string;
  history: DividendCredit[];
  projected: ProjectedDividend[];
};

export function getDividends(): Promise<DividendSummary> {
  return authedGet<DividendSummary>("/v1/portfolio/dividends");
}

// ---------------------------------------------------------------------------
// Pending orders
// ---------------------------------------------------------------------------

export type OrderType = "limit" | "stop_loss" | "take_profit";
export type OrderStatus = "pending" | "filled" | "cancelled";

export type PendingOrder = {
  id: number;
  ticker: string;
  side: "buy" | "sell";
  order_type: OrderType;
  quantity: string;
  limit_price: string;
  status: OrderStatus;
  created_at: string;
  filled_at: string | null;
  fill_price: string | null;
};

export type PendingOrderInput = {
  ticker: string;
  side: "buy" | "sell";
  order_type: OrderType;
  quantity: string;
  limit_price: string;
};

export function listOrders(status?: OrderStatus): Promise<PendingOrder[]> {
  const qs = status ? `?status=${status}` : "";
  return authedGet<PendingOrder[]>(`/v1/orders${qs}`);
}

export function createOrder(body: PendingOrderInput): Promise<PendingOrder> {
  return authedPost<PendingOrder>("/v1/orders", body);
}

export function cancelOrder(orderId: number): Promise<void> {
  return authedDelete(`/v1/orders/${orderId}`);
}
