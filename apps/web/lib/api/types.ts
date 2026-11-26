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

import type { components } from "./schema";

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
  /** A3.1: raw exchange prices are stored, so the chart can offer `adjustment=raw`. */
  has_raw?: boolean;
  /** A3.5: the market and venue index (RS pane label), and NSE/BSE (delivery pane). */
  market?: "US" | "IN" | null;
  benchmark?: string | null;
  benchmark_name?: string | null;
  is_indian?: boolean;
  /** A6.2: the intraday bars stored for the symbol (best feed), or null. */
  intraday?: IntradayInfo | null;
};

/** A6.2: which intraday intervals a symbol has (`SymbolDetailOut.intraday`). */
export type IntradayInfo = {
  feed: string;
  badge: string;
  intervals: ("1m" | "5m" | "15m" | "30m" | "60m")[];
  first: string;
  last: string;
  venue: string;
  time_zone: string;
  feeds: string[];
};

/** The intervals the bars, indicators and AVWAP routes take. */
export type ApiInterval = "1d" | "1wk" | "1mo" | "1m" | "5m" | "15m" | "30m" | "60m";

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
  /** The stored bar's provenance; "mixed" on a resampled bar whose days disagree. */
  source?: string | null;
  adjustment_semantics?: string | null;
  /** A1.4a, weekly/monthly only: daily bars in the period, and whether it is not over. */
  sessions?: number | null;
  partial?: boolean | null;
  /**
   * A6.2, intraday only: `ts` is the bar's open (UTC), `closed_at` its close,
   * `session_date` the venue's date of its session, `feed`/`badge` its source
   * and `minutes` the stored minutes in it.
   */
  closed_at?: string | null;
  session_date?: string | null;
  feed?: string | null;
  badge?: string | null;
  minutes?: number | null;
};

/** "mixed" (strong signals both ways) comes from Aegis News (audit AG-4). */
export type Sentiment = "positive" | "neutral" | "negative" | "mixed";

/**
 * One Aegis News document linked to StockViz symbols (Phase 2). No article
 * text or image. `available_at` is when Aegis had it; `published_at` is the
 * publisher's claim and is often missing (audit AG-12).
 */
export type NewsArticle = {
  id: string;
  tickers: string[];
  title: string;
  url: string | null;
  source: string;
  published_at: string | null;
  available_at: string;
  sentiment: Sentiment | null;
  sentiment_model: string | null;
  topic: string | null;
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

export type IndicatorMeta = {
  label: string;
  pane: "price" | "separate";
  outputs: string[];
  params: Record<string, number>;
  lookback: number;
  group: string;
  anchored?: "none" | "start";
};

export type Indicators = {
  ticker: string;
  /** "rsi_14" for one output; "bb_20_2.upper" for an indicator with several. */
  series: Record<string, IndicatorPoint[]>;
  macd: MACDPoint[] | null;
  /** Phase 6.1: per requested name, where it draws and what it outputs. */
  meta?: Record<string, IndicatorMeta>;
  warmup_bars?: number;
  /** A1.4a: the interval they ran on; a partial newest bar is left out of the inputs. */
  interval?: string;
  partial_bar_excluded?: string | null;
  /** A6.2: the intraday feed they ran on. */
  feed?: string | null;
};

/** A3.4: one study parameter and its bounds, from `/v1/indicators/catalog`. */
export type IndicatorParam = {
  name: string;
  label: string;
  type: "int" | "float";
  default: number;
  min: number;
  max: number;
  /** Decimals must be above `min`; whole numbers may equal it. */
  min_exclusive: boolean;
  step: number;
  /** Names for the values 1..n when the parameter picks an option. */
  choices: string[];
};

/** A3.4: a study's canonical signal (default parameters) and its evidence grade. */
export type IndicatorSignal = {
  rule: string;
  hash: string;
  description: string;
  source: string;
  evidence?: ChecklistEvidence | null;
};

export type IndicatorCatalogItem = {
  key: string;
  label: string;
  params: string[];
  defaults: number[];
  outputs: string[];
  pane: "price" | "separate";
  group: string;
  parameters: IndicatorParam[];
  default_key: string;
  anchored: "none" | "start";
  description: string;
  source: string;
  /** Null: no canonical signal, so "No grade". */
  signal?: IndicatorSignal | null;
};

/** A2.4: met, not met, or unknown (an input is missing and nothing failed). */
export type ChecklistStatus = "met" | "not_met" | "unknown";
export type ChecklistGrade = "A" | "B" | "C" | "D" | "insufficient";
export type ChecklistScope = "all" | "india" | "other";

/** The latest evidence study of one dimension setup version (association, not advice). */
export type ChecklistEvidence = {
  grade: ChecklistGrade;
  n_events: number;
  symbols: number;
  horizon: number;
  window_start: string;
  window_end: string;
  mean_excess?: number | null;
  t_stat?: number | null;
  hit_rate?: number | null;
  mean_net_return?: number | null;
  base_rate?: number | null;
  overlapping_skipped: number;
  universe: BacktestUniverse;
  computed_at: string;
};

export type ChecklistConditionDef = { label: string; rule: string };

/** One setup of a dimension: every listing, or Indian / other listings (delivery). */
export type ChecklistVariant = {
  scope: ChecklistScope;
  setup_id: number;
  setup_version_id: number;
  version: number;
  canonical: string;
  hash: string;
  conditions: ChecklistConditionDef[];
  evidence?: ChecklistEvidence | null;
};

export type ChecklistDimension = {
  key: string;
  name: string;
  summary: string;
  source: string;
  variants: ChecklistVariant[];
};

export type ChecklistCondition = {
  label: string;
  rule: string;
  status: ChecklistStatus;
  reason?: string | null;
};

export type ChecklistResult = {
  key: string;
  scope: ChecklistScope;
  setup_version_id?: number | null;
  status: ChecklistStatus;
  reason?: string | null;
  conditions?: ChecklistCondition[];
};

export type ChecklistRow = {
  ticker: string;
  name: string;
  sector?: string | null;
  currency?: string | null;
  session_date: string;
  met: number;
  evaluated: number;
  total: number;
  results: ChecklistResult[];
  computed_at: string;
  stale: boolean;
};

export type Checklist = {
  dimensions: ChecklistDimension[];
  rows: ChecklistRow[];
  total: number;
  universe: BacktestUniverse;
  disclaimer: string;
};

export type SymbolChecklist = {
  ticker: string;
  dimensions: ChecklistDimension[];
  row?: ChecklistRow | null;
  universe: BacktestUniverse;
  disclaimer: string;
};

export type ScreenerResult = {
  ticker: string;
  name: string;
  sector: string | null;
  exchange: string | null;
  currency: string;
  last_close: string;
  /** Date (`YYYY-MM-DD`) of the bar behind last_close and the metrics. */
  as_of: string | null;
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
  /** "price" (default) ignores dividends; "total" credits them on ex-dates (SR-7). */
  return_mode?: "price" | "total";
  /** Phase 5.3: "next_open" (default) or "next_close". */
  fill_rule?: "next_open" | "next_close";
  /** Moves the fill price against the trader by half the spread. */
  spread_bps?: number;
  /** Must match the symbol's currency (Phase 5.6); "none" fits any. A4.2:
   * "auto" (the default) picks the symbol's market; old names still work. */
  fee_schedule?: components["schemas"]["BacktestIn"]["fee_schedule"];
  /** A4.2: Indian brokerage model. */
  brokerage?: "zerodha" | "zero";
  /** A4.2: % of the 20-day average traded value a buy may take; null: off. */
  adv_cap_pct?: number | null;
  /** A4.3: the last 20% of the range is held out unless "none". */
  holdout?: components["schemas"]["BacktestIn"]["holdout"];
};

export type BacktestTrade = {
  date: string;
  side: "buy" | "sell";
  price: string;
  shares: string;
  /** Phase 5.3: the price before spread and slippage, and each fee charged. */
  reference_price?: string | null;
  fees?: { name: string; amount: string }[];
  /** A4.2: the shares asked for when the ADV cap bought fewer. */
  requested_shares?: string | null;
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
  /** A4.2, net first: the figures above are after costs; these add them back. */
  gross_return: number;
  gross_final_nav: string;
  total_fees: string;
  price_costs: string;
};

export type BacktestResult = {
  ticker: string;
  /** Phase 5.2: amounts are in the symbol's currency (audit SR-11). */
  currency?: string;
  /** Stored bars' basis, e.g. "split_adjusted", or "mixed" (audit SR-7). */
  price_basis?: string | null;
  return_mode?: "price" | "total";
  /** Bars before the start the strategy saw but did not trade (audit SR-3). */
  warmup_bars?: number;
  /** Kernel profile, e.g. "next_open/v1", and the fee schedule used. */
  execution_profile?: string;
  fee_schedule?: string;
  trades: BacktestTrade[];
  equity_curve: BacktestEquityPoint[];
  summary: BacktestSummary;
  /** A1.4a: the universe it ran on; "pinned" today, survivorship-biased. */
  universe?: BacktestUniverse;
  /** A4.2: each fee component with its rate and source, and the ADV cap. */
  costs?: components["schemas"]["CostsOut"] | null;
  liquidity?: components["schemas"]["LiquidityOut"] | null;
  /** A4.3: the window used, the report card, and the trial ledger's checks. */
  window?: components["schemas"]["RunWindowOut"] | null;
  report?: components["schemas"]["ReportCardOut"] | null;
  checks?: components["schemas"]["OverfittingChecksOut"] | null;
};

export type BacktestUniverse = {
  name: string;
  point_in_time: boolean;
  survivorship_biased: boolean;
  note: string;
};

export type MarketSummaryRow = {
  ticker: string;
  name: string;
  sector: string | null;
  exchange: string | null;
  currency: string;
  last_close: string | null;
  /** Timestamp of the stored bar behind last_close; null without stored bars. */
  last_close_at: string | null;
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
