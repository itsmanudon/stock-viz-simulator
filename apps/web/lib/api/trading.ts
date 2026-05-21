import "server-only";

import { authedDelete, authedGet, authedPost } from "./server";

export type Position = {
  ticker: string;
  name: string;
  quantity: string;
  // ISO-4217 ccy the symbol trades in.
  currency: string;
  // avg_cost / last_close are in the symbol's native currency.
  avg_cost: string;
  last_close: string | null;
  // Native-currency aggregates.
  market_value_native: string;
  unrealized_pl_native: string;
  // Aggregates converted to the portfolio's display currency.
  market_value: string;
  unrealized_pl: string;
};

export type Portfolio = {
  portfolio_id: number;
  // All top-level aggregates (cash + market value + totals) are in this currency.
  display_currency: string;
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
  // Per-share fill price in the symbol's native currency.
  price: string;
  ts: string;
  // ISO-4217 ccy the trade is denominated in (== symbol's currency).
  currency: string;
  // USD per 1 unit of `currency` (1 for USD symbols).
  fx_rate: string;
  total_native: string;
  total_usd: string;
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

// ---------------------------------------------------------------------------
// Portfolio analytics
// ---------------------------------------------------------------------------

export type SectorAllocation = {
  sector: string;
  market_value: string;
  pct: number;
};

export type TopMover = {
  ticker: string;
  name: string;
  sector: string | null;
  unrealized_pl: string;
  return_pct: number;
};

export type PortfolioAnalytics = {
  display_currency: string;
  history_days: number;
  total_return_pct: number | null;
  annualised_return_pct: number | null;
  sharpe_ratio: number | null;
  max_drawdown_pct: number | null;
  risk_free_rate: number;
  sector_allocation: SectorAllocation[];
  top_gainers: TopMover[];
  top_losers: TopMover[];
};

export function getPortfolioAnalytics(): Promise<PortfolioAnalytics> {
  return authedGet<PortfolioAnalytics>("/v1/portfolio/analytics");
}
