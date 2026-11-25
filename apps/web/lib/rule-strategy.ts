/**
 * A4.1: the Rule strategy mode of /backtest. Pure helpers: the form state
 * turned into a `POST /v1/backtest/strategy` body, the result's trades as
 * chart markers, and the words for each exit reason. Browser-safe (types
 * only from the API schema).
 */

import type { components } from "./api/schema";

export type StrategyRequest = components["schemas"]["StrategyBacktestIn"];
export type StrategyResult = components["schemas"]["StrategyBacktestOut"];
export type StrategyTrade = components["schemas"]["StrategyTradeOut"];
export type StrategyReason = StrategyTrade["reason"];
export type SizingKind = NonNullable<components["schemas"]["StrategySizingIn"]["kind"]>;
export type FeeSchedule = StrategyRequest["fee_schedule"];

export type RuleField = {
  text: string;
  /** Set when a saved setup's version was loaded and not edited since. */
  versionId: number | null;
};

export type UniverseKind = "ticker" | "watchlist" | "list";

export type StrategyForm = {
  entry: RuleField;
  exit: RuleField;
  universeKind: UniverseKind;
  ticker: string;
  watchlistId: string;
  tickerList: string;
  from: string;
  to: string;
  initialCash: string;
  fillRule: "next_open" | "next_close";
  feeSchedule: FeeSchedule;
  commissionBps: string;
  slippageBps: string;
  spreadBps: string;
  useFixed: boolean;
  fixedPct: string;
  useAtr: boolean;
  atrMultiple: string;
  atrPeriod: string;
  useTrail: boolean;
  trailKind: "atr" | "pct";
  trailValue: string;
  trailPeriod: string;
  useTime: boolean;
  timeBars: string;
  sizing: SizingKind;
  fraction: string;
  riskPct: string;
  maxPositions: string;
  direction: "long" | "short";
  shortable: string;
};

/** Short marker labels, so a busy chart stays readable (the table has the words). */
export const REASON_CODE: Record<StrategyReason, string> = {
  exit_rule: "X",
  stop_fixed: "SL",
  stop_atr: "ATR",
  trail: "TS",
  time: "T",
  end_of_data: "",
};

export const REASON_LABEL: Record<StrategyReason, string> = {
  exit_rule: "Exit rule",
  stop_fixed: "Fixed stop",
  stop_atr: "ATR stop",
  trail: "Trailing stop",
  time: "Time stop",
  end_of_data: "Still open",
};

/** "AAPL, msft  nvda" -> ["AAPL", "MSFT", "NVDA"], de-duplicated, at most 50. */
export function parseTickerList(raw: string): string[] {
  const seen = new Set<string>();
  for (const part of raw.split(/[\s,;]+/)) {
    const t = part.trim().toUpperCase();
    if (t) seen.add(t);
  }
  return [...seen].slice(0, 50);
}

function num(raw: string): number {
  return Number(raw);
}

function rule(field: RuleField): StrategyRequest["entry"] {
  return field.versionId !== null
    ? { setup_version_id: field.versionId }
    : { rule: field.text.trim() };
}

/** The form as the API's request body. */
export function buildStrategyRequest(form: StrategyForm): StrategyRequest {
  const universe: StrategyRequest["universe"] =
    form.universeKind === "ticker"
      ? { ticker: form.ticker }
      : form.universeKind === "watchlist"
        ? { watchlist_id: Number(form.watchlistId) }
        : { tickers: parseTickerList(form.tickerList) };
  const stops: NonNullable<StrategyRequest["stops"]> = {};
  if (form.useFixed) stops.fixed_pct = num(form.fixedPct);
  if (form.useAtr) stops.atr = { multiple: num(form.atrMultiple), period: num(form.atrPeriod) };
  if (form.useTrail) {
    stops.trailing = {
      kind: form.trailKind,
      value: num(form.trailValue),
      period: num(form.trailPeriod),
    };
  }
  if (form.useTime) stops.time_bars = num(form.timeBars);
  const sizing: NonNullable<StrategyRequest["sizing"]> = { kind: form.sizing };
  if (form.sizing === "fixed_fraction") sizing.fraction = num(form.fraction) / 100;
  if (form.sizing === "fixed_risk") sizing.risk_pct = num(form.riskPct);
  if (form.universeKind !== "ticker" && form.maxPositions.trim()) {
    sizing.max_positions = num(form.maxPositions);
  }
  const request: StrategyRequest = {
    entry: rule(form.entry),
    exit: form.exit.text.trim() || form.exit.versionId !== null ? rule(form.exit) : null,
    stops,
    sizing,
    universe,
    from: form.from,
    to: form.to,
    initial_cash: form.initialCash,
    fill_rule: form.fillRule,
    fee_schedule: form.feeSchedule,
    commission_bps: num(form.commissionBps) || 0,
    slippage_bps: num(form.slippageBps) || 0,
    spread_bps: num(form.spreadBps) || 0,
    direction: form.direction,
    shortable: form.direction === "short" ? parseTickerList(form.shortable) : [],
  };
  return request;
}

/** Why the run button is off, or null when the form can run. */
export function formProblem(form: StrategyForm, rulesValid: boolean): string | null {
  if (!form.entry.text.trim() && form.entry.versionId === null) return "Write an entry rule.";
  if (!rulesValid) return "Fix the rule first.";
  if (form.universeKind === "watchlist" && !form.watchlistId) return "Pick a watchlist.";
  if (form.universeKind === "list" && parseTickerList(form.tickerList).length === 0) {
    return "List at least one ticker.";
  }
  if (form.sizing === "fixed_risk" && !form.useFixed && !form.useAtr && !form.useTrail) {
    return "Fixed-risk sizing needs a fixed, ATR or trailing stop.";
  }
  return null;
}

export type TradeMarker = {
  time: string;
  position: "aboveBar" | "belowBar";
  color: string;
  shape: "arrowUp" | "arrowDown" | "circle";
  text: string;
};

/**
 * One marker at each entry and exit of `ticker`'s trades. Long entries are
 * up arrows under the bar, exits down arrows above it (mirrored for shorts);
 * an exit says why it happened, and a gap through the stop says "gap".
 * Trades still open at the end have no exit marker.
 */
export function tradeMarkers(
  trades: StrategyTrade[],
  ticker: string,
  colours: { entry: string; exit: string },
): TradeMarker[] {
  const out: TradeMarker[] = [];
  for (const t of trades) {
    if (t.ticker !== ticker) continue;
    const long = t.direction === "long";
    out.push({
      time: `${t.entry_date}T00:00:00`,
      position: long ? "belowBar" : "aboveBar",
      color: colours.entry,
      shape: long ? "arrowUp" : "arrowDown",
      text: long ? "B" : "S",
    });
    if (t.open) continue;
    out.push({
      time: `${t.exit_date}T00:00:00`,
      position: long ? "aboveBar" : "belowBar",
      color: colours.exit,
      shape: long ? "arrowDown" : "arrowUp",
      text: `${REASON_CODE[t.reason]}${t.gap ? " gap" : ""}`,
    });
  }
  return out.sort((a, b) => a.time.localeCompare(b.time));
}

/** "+1.25R" / "-1.00R" / "–" */
export function formatR(r: number | null | undefined): string {
  if (r === null || r === undefined) return "–";
  return `${r > 0 ? "+" : ""}${r.toFixed(2)}R`;
}
