/**
 * A4.4: the Rotation mode of /backtest. Pure helpers: the form state turned
 * into a `POST /v1/backtest/rotation` body, why the run button is off, and
 * the words for a rebalance. Browser-safe (types only from the API schema).
 */

import type { components } from "./api/schema";
import { advCapValue } from "./fees";
import { type RuleField, parseTickerList } from "./rule-strategy";

export type RotationRequest = components["schemas"]["RotationBacktestIn"];
export type RotationResult = components["schemas"]["RotationBacktestOut"];
export type RotationRebalance = components["schemas"]["RotationRebalanceOut"];
export type RotationTrade = components["schemas"]["RotationTradeOut"];

/** A7.7 (M7.5): one factor row of a multi-factor model. */
export type FactorRow = {
  name: string;
  expression: string;
  weight: string;
  higherIsBetter: boolean;
};

/** The factor presets: openly defined, each a numeric Rule DSL expression. */
export const FACTOR_PRESETS: FactorRow[] = [
  {
    name: "Momentum 12-1",
    expression: "pct_change(close, 252) - pct_change(close, 21)",
    weight: "1",
    higherIsBetter: true,
  },
  { name: "Low volatility", expression: "atr(14) / close", weight: "1", higherIsBetter: false },
  { name: "Value (P/E)", expression: "fundamental.pe", weight: "1", higherIsBetter: false },
  { name: "Quality (ROE)", expression: "fundamental.roe", weight: "1", higherIsBetter: true },
  { name: "Size", expression: "fundamental.market_cap", weight: "1", higherIsBetter: false },
];

export type RotationForm = {
  /** A7.7: a single ranking, or a weighted factor model. */
  mode: "ranking" | "factors";
  factors: FactorRow[];
  ranking: string;
  topN: string;
  schedule: "weekly" | "monthly";
  weighting: "equal" | "inverse_volatility";
  buffer: string;
  useCashFilter: boolean;
  cashFilter: RuleField;
  universeKind: "watchlist" | "list";
  watchlistId: string;
  tickerList: string;
  from: string;
  to: string;
  initialCash: string;
  fillRule: "next_open" | "next_close";
  feeSchedule: NonNullable<RotationRequest["fee_schedule"]>;
  brokerage: NonNullable<RotationRequest["brokerage"]>;
  advCapPct: string;
  commissionBps: string;
  slippageBps: string;
  spreadBps: string;
  holdout: NonNullable<RotationRequest["holdout"]>;
};

export const DEFAULT_RANKING = "pct_change(close, 126)";
export const DEFAULT_CASH_FILTER = "index_close < sma(index_close, 200)";

export function initialRotationForm(
  tickers: string[],
  range: { from: string; to: string },
): RotationForm {
  return {
    mode: "ranking",
    factors: FACTOR_PRESETS.slice(0, 2),
    ranking: DEFAULT_RANKING,
    topN: "5",
    schedule: "monthly",
    weighting: "equal",
    buffer: "0",
    useCashFilter: false,
    cashFilter: { text: DEFAULT_CASH_FILTER, versionId: null },
    universeKind: "list",
    watchlistId: "",
    tickerList: tickers.join(", "),
    from: range.from,
    to: range.to,
    initialCash: "100000",
    fillRule: "next_open",
    feeSchedule: "auto",
    brokerage: "zerodha",
    advCapPct: "10",
    commissionBps: "0",
    slippageBps: "0",
    spreadBps: "0",
    holdout: "last_20pct",
  };
}

function num(raw: string): number {
  return Number(raw);
}

export function buildRotationRequest(form: RotationForm): RotationRequest {
  const filter = form.cashFilter;
  return {
    ...(form.mode === "factors"
      ? {
          ranking: null,
          factors: form.factors.map((f) => ({
            name: f.name.trim() || null,
            expression: f.expression.trim(),
            weight: Number(f.weight),
            higher_is_better: f.higherIsBetter,
          })),
        }
      : { ranking: form.ranking.trim(), factors: null }),
    top_n: num(form.topN),
    schedule: form.schedule,
    weighting: form.weighting,
    buffer: num(form.buffer) || 0,
    cash_filter: form.useCashFilter
      ? filter.versionId !== null
        ? { setup_version_id: filter.versionId }
        : { rule: filter.text.trim() }
      : null,
    universe:
      form.universeKind === "watchlist"
        ? { watchlist_id: Number(form.watchlistId) }
        : { tickers: parseTickerList(form.tickerList) },
    from: form.from,
    to: form.to,
    initial_cash: form.initialCash,
    fill_rule: form.fillRule,
    fee_schedule: form.feeSchedule,
    brokerage: form.brokerage,
    adv_cap_pct: advCapValue(form.advCapPct),
    commission_bps: num(form.commissionBps) || 0,
    slippage_bps: num(form.slippageBps) || 0,
    spread_bps: num(form.spreadBps) || 0,
    holdout: form.holdout,
  };
}

/** Why the run button is off, or null when the form can run. */
export function rotationProblem(form: RotationForm, rulesValid: boolean): string | null {
  if (form.mode === "factors") {
    if (form.factors.length === 0) return "Add at least one factor.";
    if (form.factors.length > 8) return "At most 8 factors.";
    if (form.factors.some((f) => !f.expression.trim())) return "Every factor needs an expression.";
    if (form.factors.some((f) => !(Number(f.weight) > 0 && Number(f.weight) <= 10))) {
      return "Factor weights are above 0 and at most 10.";
    }
  } else {
    if (!form.ranking.trim()) return "Write a ranking expression.";
    if (!rulesValid) return "Fix the ranking or the cash filter first.";
  }
  const n = num(form.topN);
  if (!Number.isInteger(n) || n < 1 || n > 50) return "Top N is a whole number from 1 to 50.";
  if (form.useCashFilter && !form.cashFilter.text.trim() && form.cashFilter.versionId === null) {
    return "Write the cash filter, or turn it off.";
  }
  if (form.universeKind === "watchlist" && !form.watchlistId) return "Pick a watchlist.";
  if (form.universeKind === "list") {
    const count = parseTickerList(form.tickerList).length;
    if (count < 2) return "List at least two tickers.";
    if (n > count) return `Top N (${n}) is more than the ${count} tickers listed.`;
  }
  return null;
}

/** "AAPL, MSFT" or "–". */
export function nameList(tickers: string[]): string {
  return tickers.length ? tickers.join(", ") : "–";
}

/** How a rebalance changed the book, in a few words. */
export function rebalanceSummary(r: RotationRebalance): string {
  if (r.skipped === "no_data") return "No bars that session: nothing changed";
  if (r.cash_filter === true) {
    return (r.exited ?? []).length
      ? "Cash filter met: sold everything"
      : "Cash filter met: in cash";
  }
  const entered = (r.entered ?? []).length;
  const exited = (r.exited ?? []).length;
  if (!entered && !exited) return "No change";
  return `${entered} in, ${exited} out`;
}

/** Turnover as "26.6%". */
export function turnoverLabel(fraction: number): string {
  return `${(fraction * 100).toFixed(1)}%`;
}

/** "US" for a plain ticker, "IN" for NSE/BSE, null for indices and other markets. */
export function symbolMarket(ticker: string): "US" | "IN" | null {
  if (ticker.startsWith("^")) return null;
  if (ticker.endsWith(".NS") || ticker.endsWith(".BO")) return "IN";
  return ticker.includes(".") ? null : "US";
}

/** Up to 50 symbols of a market with stored closes (all of them when no close is known). */
export function marketTickers(
  symbols: { ticker: string; lastClose?: string | null }[],
  market: "US" | "IN",
): string[] {
  const inMarket = symbols.filter((s) => symbolMarket(s.ticker) === market);
  const known = inMarket.some((s) => s.lastClose !== undefined);
  return inMarket
    .filter((s) => !known || s.lastClose)
    .map((s) => s.ticker)
    .slice(0, 50);
}

/** Ten years of history ending at the latest close (or today without one). */
export function rotationRange(
  lastClose: string | null | undefined,
  today: Date = new Date(),
): { from: string; to: string } {
  const to =
    lastClose && /^\d{4}-\d{2}-\d{2}$/.test(lastClose)
      ? lastClose
      : today.toISOString().slice(0, 10);
  const start = new Date(`${to}T00:00:00Z`);
  start.setUTCFullYear(start.getUTCFullYear() - 10);
  return { from: start.toISOString().slice(0, 10), to };
}
