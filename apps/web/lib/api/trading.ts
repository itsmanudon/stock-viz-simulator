import "server-only";

import { authedDelete, authedGet, authedPost, authedPut } from "./server";

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
  reserved_quantity: string;
  available_quantity: string;
};

export type Portfolio = {
  portfolio_id: number;
  // All top-level aggregates (cash + market value + totals) are in this currency.
  display_currency: string;
  cash_balance: string;
  reserved_cash: string;
  available_cash: string;
  market_value: string;
  total_value: string;
  total_cost_basis: string;
  /** #68 (Phase 8.1): equities plus open options; the parts follow. */
  unrealized_pl: string;
  unrealized_pl_equity: string;
  unrealized_pl_options: string;
  /** Lifetime realized P&L; closes with no stored realization are counted, not estimated. */
  realized_pl: string;
  realized_pl_unavailable: number;
  /** Mark-to-model value of open option contracts, included in total_value. */
  options_market_value: string;
  positions: Position[];
  option_positions: PortfolioOption[];
  /** What total_value leaves out; empty when complete (audit LG-13). */
  valuation_warnings: ValuationWarning[];
  /**
   * Cash per currency, base first (Phase 4.5b): a sale of a EUR stock keeps
   * its euros. cash_balance is their total; available_cash is the base's
   * buying power only. A response cached before 4.5b lacks it, so readers use `?? []`.
   */
  cash_by_currency: CurrencyCash[];
  /**
   * Phase 4.8: the account's base currency (USD or INR): cash, buying power,
   * realized P&L and the NAV history are kept in it. Locked once the account
   * has any trade, order or option. Optional for responses cached before it.
   */
  base_currency: string;
  base_currency_locked: boolean;
};

export type CurrencyCash = {
  currency: string;
  /** In `currency`. */
  amount: string;
  /** In the portfolio's display currency. */
  value: string;
};

export type ValuationWarning = {
  /** no_close / no_option_price: valued at 0. no_fx_rate: added unconverted. */
  code: "no_close" | "no_option_price" | "no_fx_rate";
  /** The ticker, or the currency for no_fx_rate. */
  subject: string;
  message: string;
};

export type PortfolioOption = {
  option_id: number;
  ticker: string;
  option_type: "call" | "put";
  strike: string;
  expiry: string;
  quantity: number;
  currency: string;
  premium_paid: string;
  market_value_native: string;
  market_value: string;
  unrealized_pl: string;
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
  // USD per 1 unit of `currency`. Captured at fill time; rows written before
  // that column existed fall back to the symbol's current rate, so the
  // response always carries a value.
  fx_rate: string;
  total_native: string;
  total_usd: string;
  /** Phase 4.8: the account's base currency and the trade's amount in it. */
  base_currency: string;
  total_base: string;
  /** Gain/loss in the base currency vs. the average cost. Sells only. */
  realized_pnl: string | null;
};

export type TradeInput = {
  ticker: string;
  side: "buy" | "sell";
  quantity: string;
  /** Repeats with the same key return the first fill (#67). */
  client_order_id?: string;
};

export function getPortfolio(): Promise<Portfolio> {
  return authedGet<Portfolio>("/v1/portfolio");
}

/**
 * Restart a fresh account in USD ($100,000) or INR (₹1 crore), Phase 4.8.
 * The API answers 409 once the account has any trade, order or option.
 */
export function putBaseCurrency(baseCurrency: "USD" | "INR"): Promise<Portfolio> {
  return authedPut<Portfolio>("/v1/portfolio/base-currency", { base_currency: baseCurrency });
}

/** Phase 8.5: the account's own pre-trade caps, % of NAV; null means no limit. */
export type RiskLimits = {
  max_position_pct: string | null;
  max_order_pct: string | null;
  max_sector_pct: string | null;
  max_currency_pct: string | null;
  max_var_pct: string | null;
  updated_at?: string | null;
};

export type LimitCheck = {
  limit: string;
  label: string;
  cap: number;
  value_after: number | null;
  breached: boolean;
  note?: string | null;
};

export type LimitPreview = {
  ticker: string;
  quantity: string;
  checks: LimitCheck[];
  breached: boolean;
};

export function getRiskLimits(): Promise<RiskLimits> {
  return authedGet<RiskLimits>("/v1/portfolio/limits");
}

export function putRiskLimits(limits: Omit<RiskLimits, "updated_at">): Promise<RiskLimits> {
  return authedPut<RiskLimits>("/v1/portfolio/limits", limits);
}

export function previewLimits(ticker: string, quantity: string): Promise<LimitPreview> {
  const q = new URLSearchParams({ ticker, quantity });
  return authedGet<LimitPreview>(`/v1/portfolio/limits/check?${q.toString()}`);
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
  /** The currency amount_credited is in (Phase 4.5c); base_value is the same credit in USD. */
  currency: string;
  base_value: string;
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
/** "expired": unfilled 30 days after it was placed (audit LG-6). */
export type OrderStatus = "pending" | "filled" | "cancelled" | "expired";

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
  cancel_reason: string | null;
};

export type PendingOrderInput = {
  ticker: string;
  side: "buy" | "sell";
  order_type: OrderType;
  quantity: string;
  limit_price: string;
  /** Repeats with the same key return the first order (#67). */
  client_order_id?: string;
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
  /** Phase 8.1. Optional for responses cached before it. */
  returns?: PortfolioReturns | null;
  /** Phase 8.2. Optional for responses cached before it. */
  exposure?: PortfolioExposure | null;
  attribution?: PortfolioAttribution | null;
};

export type ExposureBucket = {
  key: string;
  equity_value: string;
  cash_value: string;
  /** Open options at delta-adjusted notional: exposure, not part of NAV. */
  options_delta: string;
  weight_pct: number;
  options_delta_pct: number;
};

export type PortfolioExposure = {
  /** The display currency. */
  currency: string;
  method: string;
  basis: string;
  dimensions: { dimension: string; buckets: ExposureBucket[] }[];
};

export type HoldingAttribution = {
  ticker: string;
  currency: string;
  entry_rate: string | null;
  rate_now: string | null;
  cost_base: string | null;
  value_base: string | null;
  price_effect: string | null;
  currency_effect: string | null;
  cross_effect: string | null;
  income: string;
  reason?: string | null;
};

export type PortfolioAttribution = {
  /** The account's base currency. */
  currency: string;
  method: string;
  basis: string;
  holdings: HoldingAttribution[];
};

export type PeriodReturn = {
  period: string;
  start_date: string | null;
  end_date: string;
  return_pct: number | null;
  annualised_pct: number | null;
  reason?: string | null;
};

export type Xirr = {
  rate_pct: number | null;
  first_flow: string | null;
  flows: number;
  reason?: string | null;
};

export type PortfolioReturns = {
  /** The account's base currency: every flow and NAV is in it. */
  currency: string;
  twr_method: string;
  twr_basis: string;
  periods: PeriodReturn[];
  xirr_method: string;
  xirr_basis: string;
  account_xirr: Xirr;
  holdings: { ticker: string; kind: string; xirr: Xirr }[];
};

export type VarFigure = {
  confidence: number;
  horizon_days: number;
  scenarios: number;
  tail_count: number;
  /** Losses are positive amounts in the risk report's currency. */
  var: number;
  var_pct: number;
  cvar: number;
  cvar_pct: number;
};

/** Phase 8.3: `GET /v1/portfolio/risk`, in the account's base currency. */
export type PortfolioRisk = {
  currency: string;
  nav: number;
  method: string;
  var_rule: string;
  window: { start: string | null; end: string | null; sessions: number };
  holdings_included: number;
  excluded: { ticker: string; reason: string }[];
  proxied: { ticker: string; proxy: string; days: number }[];
  var: VarFigure[];
  monte_carlo: {
    method: string;
    paths: number;
    horizon_days: number;
    mean_block: number;
    seed: number;
    percentiles: Record<string, number>;
    prob_loss_10: number;
    prob_loss_20: number;
    /** Phase 8.6 goals: the target, and the share of paths that reach it. */
    goal?: number | null;
    prob_goal?: number | null;
  } | null;
  reason?: string | null;
};

/** Phase 8.4: `GET /v1/portfolio/stress`, in the account's base currency. */
export type StressScenario = {
  key: string;
  name: string;
  kind: "historical" | "hypothetical" | string;
  start: string | null;
  end: string | null;
  nav_before: number;
  nav_after: number;
  change: number;
  change_pct: number;
  drivers: { ticker: string; change: number }[];
  proxied: string[];
  missing: string[];
};

export type PortfolioStress = {
  currency: string;
  method: string;
  basis: string;
  scenarios: StressScenario[];
};

export function getPortfolioStress(): Promise<PortfolioStress> {
  return authedGet<PortfolioStress>("/v1/portfolio/stress");
}

export function getPortfolioRisk(goal?: number | null): Promise<PortfolioRisk> {
  const query = goal && goal > 0 ? `?goal=${encodeURIComponent(String(goal))}` : "";
  return authedGet<PortfolioRisk>(`/v1/portfolio/risk${query}`);
}

export function getPortfolioAnalytics(): Promise<PortfolioAnalytics> {
  return authedGet<PortfolioAnalytics>("/v1/portfolio/analytics");
}

export type PortfolioOverview = {
  portfolio: Portfolio;
  analytics: PortfolioAnalytics;
};

export function getPortfolioOverview(): Promise<PortfolioOverview> {
  return authedGet<PortfolioOverview>("/v1/portfolio/overview");
}
