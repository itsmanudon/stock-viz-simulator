/**
 * A4.3 (M7.4): the backtest report card and its overfitting checks. Types
 * from the API schema and pure formatting helpers, shared by both /backtest
 * modes and the saved-run pages. Browser-safe.
 */

import type { components } from "./api/schema";

type S = components["schemas"];
export type ReportCard = S["ReportCardOut"];
export type ReportMetric = S["ReportMetricOut"];
export type OverfittingChecks = S["OverfittingChecksOut"];
export type HoldoutStatus = S["HoldoutStatusOut"];
export type RunWindow = S["RunWindowOut"];
export type MonteCarloFan = S["MonteCarloFanOut"];
export type RegimeSplit = S["RegimeSplitOut"];
export type HoldoutMode = NonNullable<S["BacktestIn"]["holdout"]>;

export const HOLDOUT_OPTIONS: { value: HoldoutMode; label: string }[] = [
  { value: "last_20pct", label: "Hold out the last 20% (locked)" },
  { value: "none", label: "No holdout (use the whole range)" },
];

/** A PBO result as stored on a sweep (`services/backtest/report.py::pbo_cscv`). */
export type PboResult = {
  method: string;
  pbo: number;
  blocks: number;
  block_sessions: number;
  dropped_sessions: number;
  sessions: number;
  settings: number;
  combinations: number;
  metric: string;
  logit_median: number;
  prob_oos_loss: number;
  histogram: { lo: number; hi: number; count: number }[];
};

/** A parameter-plateau heatmap as stored on a sweep (`report.plateau`). */
export type Plateau = {
  metric: string;
  x_param: string;
  y_param: string;
  x_values: number[];
  y_values: number[];
  /** Rows by y, columns by x; null where no setting ran. */
  cells: (number | null)[][];
  best: { x: number; y: number; value: number };
  tolerance: number;
  neighbours: number;
  within: number;
  share_within: number;
  isolated: boolean;
  rule: string;
};

export function pctText(fraction: number, digits = 1): string {
  return `${(fraction * 100).toFixed(digits)}%`;
}

export function signedPct(fraction: number, digits = 2): string {
  const v = fraction * 100;
  return `${v > 0 ? "+" : ""}${v.toFixed(digits)}%`;
}

/** A metric's value in its unit; "n/a" when the API returned null. */
export function formatMetric(metric: ReportMetric, currency: string): string {
  const v = metric.value;
  if (v === null || v === undefined || !Number.isFinite(v)) return "n/a";
  switch (metric.unit) {
    case "pct":
      return metric.key === "cagr" ? signedPct(v) : pctText(v);
    case "money":
      return v.toLocaleString("en-US", { style: "currency", currency, maximumFractionDigits: 2 });
    case "r":
      return `${v >= 0 ? "+" : ""}${v.toFixed(2)} R`;
    case "days":
      return `${v.toFixed(1)} d`;
    case "count":
      return String(Math.round(v));
    default:
      return v.toFixed(2);
  }
}

/** Plain words for a probability such as PSR or DSR. */
export function probabilityWords(value: number | null | undefined): string {
  if (value === null || value === undefined) return "not defined";
  if (value >= 0.95) return "strong";
  if (value >= 0.8) return "moderate";
  if (value >= 0.5) return "weak";
  return "no evidence";
}

export const REGIME_LABEL = (state: string | null | undefined): string =>
  state ?? "Not enough data";

/** Parameter names as the sweep table writes them. */
export const PARAM_LABEL: Record<string, string> = {
  short_window: "Short SMA",
  long_window: "Long SMA",
  buy_below: "Buy below RSI",
  sell_above: "Sell above RSI",
};

/**
 * A cell's share of the way from the grid's worst to its best value, 0..1
 * (null cells stay null), for the heatmap's opacity.
 */
export function heatShare(plateau: Plateau): (number | null)[][] {
  const values = plateau.cells.flat().filter((v): v is number => v !== null);
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const span = hi - lo;
  return plateau.cells.map((row) =>
    row.map((v) => (v === null ? null : span > 0 ? (v - lo) / span : 1)),
  );
}

export function formatPlateauValue(metric: string, value: number | null): string {
  if (value === null) return "–";
  return metric === "total_return" ? signedPct(value, 1) : value.toFixed(2);
}

/**
 * A template's buy and sell legs as round trips the strategy trades chart
 * reads (entry B, exit X; a position still held at the end has no exit).
 */
export function templateRoundTrips(
  trades: { date: string; side: "buy" | "sell"; price: string; shares: string }[],
  ticker: string,
  lastDate: string | undefined,
): StrategyTradeLike[] {
  const out: StrategyTradeLike[] = [];
  let entry: { date: string; price: string; shares: string } | null = null;
  for (const t of trades) {
    if (t.side === "buy") {
      entry = t;
    } else if (entry) {
      out.push(trip(ticker, entry, t.date, t.price, false));
      entry = null;
    }
  }
  if (entry && lastDate) out.push(trip(ticker, entry, lastDate, entry.price, true));
  return out;
}

export type StrategyTradeLike = S["StrategyTradeOut"];

function trip(
  ticker: string,
  entry: { date: string; price: string; shares: string },
  exitDate: string,
  exitPrice: string,
  open: boolean,
): StrategyTradeLike {
  return {
    ticker,
    direction: "long",
    entry_date: entry.date,
    entry_price: entry.price,
    entry_reference_price: entry.price,
    exit_date: exitDate,
    exit_price: exitPrice,
    exit_reference_price: exitPrice,
    quantity: entry.shares,
    entry_fees: "0",
    exit_fees: "0",
    pnl: "0",
    return_pct: 0,
    reason: open ? "end_of_data" : "exit_rule",
    gap: false,
    open,
    bars_held: 0,
  };
}
