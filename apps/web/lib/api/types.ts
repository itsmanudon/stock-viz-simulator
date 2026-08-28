/**
 * Wire types mirroring the FastAPI Pydantic schemas in apps/api.
 *
 * Hand-typed for Phase 3. When the API surface stabilizes we'll swap to
 * openapi-typescript generation off /openapi.json — until then, keep this
 * file in sync with apps/api/src/stockviz/schemas.py.
 *
 * Numeric fields come over the wire as strings because the API uses
 * Decimal columns and pydantic serializes them as strings to preserve
 * precision. Parse to Number only at the render boundary.
 */

export type Health = {
  status: "ok" | "degraded";
  version: string;
  database: "up" | "down";
};

export type Symbol = {
  ticker: string;
  name: string;
  sector: string | null;
  exchange: string | null;
  // ISO-4217 currency the symbol trades in. Defaults to USD for the
  // historical universe; non-USD symbols (e.g. SAP.DE) declare it explicitly.
  currency: string;
  is_active: boolean;
};

export type Quote = {
  ticker: string;
  ts: string;
  close: string;
};

export type SymbolDetail = Symbol & {
  latest: Quote | null;
};

export type EarningsEvent = {
  id: number;
  ticker: string;
  name: string;
  event_date: string;
  report_time: string | null;
  fiscal_period: string | null;
  eps_estimate: string | null;
  eps_actual: string | null;
  surprise_pct: string | null;
  result: "beat" | "miss" | "in_line" | "unknown";
  source: string;
  fetched_at: string;
};

export type Bar = {
  ts: string;
  open: string;
  high: string;
  low: string;
  close: string;
  volume: number;
};

export type Sentiment = "positive" | "neutral" | "negative";

export type NewsArticle = {
  id: number;
  ticker: string | null;
  title: string;
  url: string;
  source: string | null;
  published_at: string;
  summary: string | null;
  image_url: string | null;
  sentiment: Sentiment | null;
};

export type IndicatorPoint = {
  ts: string;
  value: number;
};

export type MACDPoint = {
  ts: string;
  macd: number;
  signal: number;
  histogram: number;
};

export type Indicators = {
  ticker: string;
  series: Record<string, IndicatorPoint[]>;
  macd: MACDPoint[] | null;
};

export type RecommendationVote = {
  id: string;
  label: string;
  passed: boolean;
  detail: string;
};

export type Recommendation = {
  ticker: string;
  name: string;
  sector: string | null;
  score: number;
  rationale: string[];
  votes: RecommendationVote[];
  sentiment_7d: number | null;
  computed_at: string;
};

export type ScreenerResult = {
  ticker: string;
  name: string;
  sector: string | null;
  exchange: string | null;
  currency: string;
  last_close: string;
  rsi_14: number | null;
  momentum_pct: number | null;
  momentum_days: number | null;
  high_52w: string;
  low_52w: string;
  sentiment_7d: number | null;
};

export type BacktestStrategy =
  | { type: "rsi_threshold"; buy_below: number; sell_above: number }
  | { type: "sma_crossover"; short_window: number; long_window: number };

export type BacktestRequest = {
  ticker: string;
  from: string;
  to: string;
  initial_cash: string;
  strategy: BacktestStrategy;
  /** Charged on both legs of every round trip. Zero models a frictionless run. */
  commission_bps?: number;
  slippage_bps?: number;
};

export type BacktestTrade = {
  date: string;
  side: "buy" | "sell";
  price: string;
  shares: string;
};

export type BacktestEquityPoint = {
  date: string;
  nav: string;
};

export type BacktestSummary = {
  total_return: number;
  sharpe: number;
  max_drawdown: number;
  final_nav: string;
  /** Buy-and-hold over the same window — what the strategy had to beat. */
  benchmark_return: number;
  benchmark_final_nav: string;
  /** Strategy return minus benchmark return, in percentage points. */
  excess_return: number;
  total_costs: string;
};

export type BacktestResult = {
  ticker: string;
  trades: BacktestTrade[];
  equity_curve: BacktestEquityPoint[];
  summary: BacktestSummary;
};

export type MarketSummaryRow = {
  ticker: string;
  name: string;
  sector: string | null;
  exchange: string | null;
  currency: string;
  last_close: string | null;
  prev_close: string | null;
  change_pct: number | null;
  /** Oldest-first closes for the inline sparkline. */
  closes: string[];
};

export type MarketsSummary = {
  rows: MarketSummaryRow[];
  /** Every sector in the active universe, not just the filtered slice. */
  sectors: string[];
};
