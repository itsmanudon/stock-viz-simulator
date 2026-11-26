/**
 * URL state for /screener: the applied filters as removable chips, and the
 * sortable columns (UI audit UX-1). Pure so it can be unit-tested; the page
 * is an async server component that needs a live API.
 *
 * Every link keeps the rest of the URL: removing a chip keeps the sort, and
 * sorting keeps every filter.
 */

import type { ScreenerResult } from "@/lib/api/types";

export type ScreenerParams = {
  /** Phase 6.2: listing country ("US", "IN", ...), currency, trend, volatility, page. */
  market?: string;
  currency?: string;
  above_sma_50?: string;
  above_sma_200?: string;
  hv_max?: string;
  page?: string;
  /** Phase 6.5 fundamentals: P/E, dividend yield %, market cap (USD billions), ROE %, debt/equity. */
  pe_max?: string;
  dividend_yield_min?: string;
  mcap_min_bn?: string;
  roe_min?: string;
  de_max?: string;
  sector?: string;
  rsi_min?: string;
  rsi_max?: string;
  momentum_days?: string;
  momentum_min?: string;
  momentum_max?: string;
  near_52w_high?: string;
  near_52w_low?: string;
  sort?: string;
  dir?: string;
  /** A2.2: a Rule DSL condition that refines the filters, and what to show. */
  rule?: string;
  rule_mode?: string;
};

const PARAM_KEYS = [
  "market",
  "currency",
  "above_sma_50",
  "above_sma_200",
  "hv_max",
  "pe_max",
  "dividend_yield_min",
  "mcap_min_bn",
  "roe_min",
  "de_max",
  "sector",
  "rsi_min",
  "rsi_max",
  "momentum_days",
  "momentum_min",
  "momentum_max",
  "near_52w_high",
  "near_52w_low",
  "sort",
  "dir",
  "page",
  "rule",
  "rule_mode",
] as const satisfies readonly (keyof ScreenerParams)[];

export type ScreenerSortKey =
  | "ticker"
  | "price"
  | "rsi"
  | "momentum"
  | "trend"
  | "volatility"
  | "pe"
  | "mcap";

/** The API's sort column for each sortable column (Phase 6.2, sorted server-side). */
export const API_SORT: Record<ScreenerSortKey, string> = {
  ticker: "ticker",
  price: "last_close",
  rsi: "rsi_14",
  momentum: "momentum_pct",
  trend: "sma_200_gap_pct",
  volatility: "hv_20",
  pe: "pe",
  mcap: "market_cap_usd",
};

export const MARKET_LABEL: Record<string, string> = {
  US: "United States",
  IN: "India",
  GB: "United Kingdom",
  DE: "Germany",
  JP: "Japan",
  CA: "Canada",
};
export type SortDir = "asc" | "desc";

export type FilterChip = { id: string; label: string; removeHref: string };

function present(value: string | undefined): value is string {
  return value !== undefined && value !== "" && Number.isFinite(Number(value));
}

function href(params: ScreenerParams, drop: readonly (keyof ScreenerParams)[] = []): string {
  const next = new URLSearchParams();
  // Any change to filters or sort starts again from the first page.
  const dropping = [...drop, ...(drop.includes("page") ? [] : (["page"] as const))];
  for (const key of PARAM_KEYS) {
    const value = params[key];
    if (value && !dropping.includes(key)) next.set(key, value);
  }
  const qs = next.toString();
  return qs ? `/screener?${qs}` : "/screener";
}

function range(min: string | undefined, max: string | undefined, unit = ""): string | null {
  const lo = present(min) ? `${min}${unit}` : null;
  const hi = present(max) ? `${max}${unit}` : null;
  if (lo && hi) return `${lo} to ${hi}`;
  if (lo) return `at least ${lo}`;
  if (hi) return `at most ${hi}`;
  return null;
}

/**
 * One chip per applied filter. RSI bounds share a chip, and so do the
 * momentum window and its bounds: the bounds mean nothing without the window
 * (the API ignores them), so they never get a chip of their own.
 */
export function activeFilterChips(params: ScreenerParams): FilterChip[] {
  const chips: FilterChip[] = [];
  if (params.market) {
    chips.push({
      id: "market",
      label: `Market: ${params.market
        .split(",")
        .map((m) => MARKET_LABEL[m] ?? m)
        .join(", ")}`,
      removeHref: href(params, ["market"]),
    });
  }
  if (params.currency) {
    chips.push({
      id: "currency",
      label: `Currency: ${params.currency}`,
      removeHref: href(params, ["currency"]),
    });
  }
  for (const [key, label] of [
    ["above_sma_50", "50-day average"],
    ["above_sma_200", "200-day average"],
  ] as const) {
    if (params[key] === "true" || params[key] === "false") {
      chips.push({
        id: key,
        label: `${params[key] === "true" ? "Above" : "Below"} ${label}`,
        removeHref: href(params, [key]),
      });
    }
  }
  const fundamentalChips: [keyof ScreenerParams, (v: string) => string][] = [
    ["pe_max", (v) => `P/E at most ${v}`],
    ["dividend_yield_min", (v) => `Dividend yield at least ${v}%`],
    ["mcap_min_bn", (v) => `Market cap at least ${v}B USD`],
    ["roe_min", (v) => `ROE at least ${v}%`],
    ["de_max", (v) => `Debt/equity at most ${v}`],
  ];
  for (const [key, label] of fundamentalChips) {
    const value = params[key];
    if (present(value)) {
      chips.push({ id: key, label: label(value), removeHref: href(params, [key]) });
    }
  }
  if (present(params.hv_max)) {
    chips.push({
      id: "hv_max",
      label: `Volatility at most ${params.hv_max}%`,
      removeHref: href(params, ["hv_max"]),
    });
  }
  if (params.sector) {
    chips.push({
      id: "sector",
      label: `Sector: ${params.sector}`,
      removeHref: href(params, ["sector"]),
    });
  }
  const rsi = range(params.rsi_min, params.rsi_max);
  if (rsi) {
    chips.push({
      id: "rsi",
      label: `RSI ${rsi}`,
      removeHref: href(params, ["rsi_min", "rsi_max"]),
    });
  }
  if (present(params.momentum_days)) {
    const bounds = range(params.momentum_min, params.momentum_max, "%");
    const drop = ["momentum_days", "momentum_min", "momentum_max"] as const;
    chips.push({
      id: "momentum",
      label: `${params.momentum_days}-day momentum${bounds ? ` ${bounds}` : ""}`,
      // The momentum column only exists with a window, so a momentum sort
      // goes with it.
      removeHref: href(params, params.sort === "momentum" ? [...drop, "sort", "dir"] : drop),
    });
  }
  if (params.near_52w_high === "true") {
    chips.push({
      id: "near_52w_high",
      label: "Near 52-week high",
      removeHref: href(params, ["near_52w_high"]),
    });
  }
  if (params.near_52w_low === "true") {
    chips.push({
      id: "near_52w_low",
      label: "Near 52-week low",
      removeHref: href(params, ["near_52w_low"]),
    });
  }
  const rule = params.rule?.trim();
  if (rule) {
    const short = rule.replace(/\s+/g, " ");
    chips.push({
      id: "rule",
      label: `Rule: ${short.length > 40 ? `${short.slice(0, 39)}…` : short}`,
      removeHref: href(params, ["rule", "rule_mode"]),
    });
  }
  return chips;
}

/** Clears every filter but keeps the sort. */
export function clearFiltersHref(params: ScreenerParams): string {
  return href({ sort: params.sort, dir: params.dir });
}

// --- A2.2: the rule ----------------------------------------------------------

export type RuleMode = "met_only" | "all";

/** The rule in the URL, trimmed; undefined when there is none. */
export function activeRule(params: ScreenerParams): string | undefined {
  const rule = params.rule?.trim();
  return rule ? rule : undefined;
}

/** "met_only" (only rows the rule met) unless the URL asks for every row. */
export function parseRuleMode(params: ScreenerParams): RuleMode {
  return params.rule_mode === "all" ? "all" : "met_only";
}

/** The same screen without its rule (the filters and sort stay). */
export function clearRuleHref(params: ScreenerParams): string {
  return href(params, ["rule", "rule_mode"]);
}

/** The same screen with the rule's other mode. */
export function ruleModeHref(params: ScreenerParams, mode: RuleMode): string {
  return href({ ...params, rule_mode: mode === "all" ? "all" : undefined });
}

/**
 * Hidden fields that carry the rest of the screen through a GET form: the
 * rule form keeps the filters and sort, the filter form keeps the rule. The
 * page is never carried, so any change starts again from page 1.
 */
export function carriedFields(
  params: ScreenerParams,
  omit: readonly (keyof ScreenerParams)[],
): [string, string][] {
  const out: [string, string][] = [];
  for (const key of PARAM_KEYS) {
    const value = params[key];
    if (value && key !== "page" && !omit.includes(key)) out.push([key, value]);
  }
  return out;
}

export type RuleErrorDetail = {
  kind: "syntax" | "type";
  message: string;
  line?: number | null;
  column?: number | null;
};

/**
 * The rule error inside an API error message ("API 422 /v1/screener?...:
 * {"detail": {...}}"), or null when the message carries none.
 */
export function ruleErrorFromMessage(message: string): RuleErrorDetail | null {
  const start = message.indexOf("{");
  if (start < 0) return null;
  try {
    const body = JSON.parse(message.slice(start)) as { detail?: unknown };
    const detail = body.detail as Partial<RuleErrorDetail> | undefined;
    if (
      detail &&
      typeof detail === "object" &&
      (detail.kind === "syntax" || detail.kind === "type") &&
      typeof detail.message === "string"
    ) {
      return {
        kind: detail.kind,
        message: detail.message,
        line: detail.line ?? null,
        column: detail.column ?? null,
      };
    }
  } catch {
    return null;
  }
  return null;
}

/** "Syntax error at line 1, column 25: unexpected 'andd'". */
export function describeRuleError(error: RuleErrorDetail): string {
  const where = error.line && error.column ? ` at line ${error.line}, column ${error.column}` : "";
  return `${error.kind === "syntax" ? "Syntax" : "Type"} error${where}: ${error.message}`;
}

/** How many daily bars the rule needs before it can be judged, in words. */
export function warmupLabel(
  bars: number | null | undefined,
  wholeHistory: boolean,
  /** A6.4: an intraday rule counts its warm-up in that timeframe's bars. */
  timeframe = "daily",
): string {
  if (wholeHistory || bars === null || bars === undefined) return "Reads the whole history";
  if (bars === 0) return "Needs no warm-up";
  const unit = timeframe === "daily" ? "daily" : timeframe === "60m" ? "1h" : timeframe;
  return `Needs ${bars} ${unit} bar${bars === 1 ? "" : "s"} of warm-up`;
}

export const RULE_RESULT_LABEL: Record<"met" | "not_met" | "unknown", string> = {
  met: "Met",
  not_met: "Not met",
  unknown: "Unknown",
};

/** The sort the URL asks for, falling back to ticker A-Z when it is invalid. */
export function parseScreenerSort(params: ScreenerParams): {
  sort: ScreenerSortKey;
  dir: SortDir;
} {
  const keys: ScreenerSortKey[] = ["ticker", "price", "rsi", "trend", "volatility", "pe", "mcap"];
  if (present(params.momentum_days)) keys.push("momentum");
  const sort = keys.find((key) => key === params.sort) ?? "ticker";
  const dir: SortDir =
    params.dir === "asc" || params.dir === "desc" ? params.dir : sort === "ticker" ? "asc" : "desc";
  return { sort, dir };
}

/** Header link: first click on a number column is biggest first. */
export function screenerSortHref(target: ScreenerSortKey, params: ScreenerParams): string {
  const current = parseScreenerSort(params);
  const dir: SortDir =
    current.sort === target
      ? current.dir === "asc"
        ? "desc"
        : "asc"
      : target === "ticker"
        ? "asc"
        : "desc";
  return href({ ...params, sort: target, dir });
}

/**
 * Sort a copy of the rows. A missing value sorts last in both directions:
 * unknown is not the worst. Price compares the stored close as a number, so
 * rows in different currencies sort by face value, as on /markets.
 */
export function sortScreenerRows(
  rows: ScreenerResult[],
  sort: ScreenerSortKey,
  dir: SortDir,
): ScreenerResult[] {
  const factor = dir === "asc" ? 1 : -1;
  if (sort === "ticker") {
    return [...rows].sort((a, b) => a.ticker.localeCompare(b.ticker) * factor);
  }
  const pick = (row: ScreenerResult): number | null => {
    const value =
      sort === "price" ? Number(row.last_close) : sort === "rsi" ? row.rsi_14 : row.momentum_pct;
    return value === null || !Number.isFinite(value) ? null : value;
  };
  return [...rows].sort((a, b) => {
    const av = pick(a);
    const bv = pick(b);
    if (av === null && bv === null) return a.ticker.localeCompare(b.ticker);
    if (av === null) return 1;
    if (bv === null) return -1;
    return (av - bv) * factor || a.ticker.localeCompare(b.ticker);
  });
}

/** The 1-based page the URL asks for. */
export function parseScreenerPage(params: ScreenerParams): number {
  const page = Number(params.page);
  return Number.isInteger(page) && page >= 1 ? page : 1;
}

/** A link to another page of the same screen. */
export function screenerPageHref(params: ScreenerParams, page: number): string {
  const next = new URLSearchParams();
  for (const key of PARAM_KEYS) {
    const value = params[key];
    if (value && key !== "page") next.set(key, value);
  }
  if (page > 1) next.set("page", String(page));
  const qs = next.toString();
  return qs ? `/screener?${qs}` : "/screener";
}

/** The current screen as the API query for /v1/screener (Phase 6.2). */
export function screenerApiQuery(params: ScreenerParams, pageSize: number): URLSearchParams {
  const q = new URLSearchParams();
  for (const key of [
    "market",
    "currency",
    "sector",
    "rsi_min",
    "rsi_max",
    "momentum_days",
    "momentum_min",
    "momentum_max",
    "near_52w_high",
    "near_52w_low",
    "above_sma_50",
    "above_sma_200",
    "hv_max",
  ] as const) {
    const value = params[key];
    if (value) q.set(key, value);
  }
  if (!present(params.momentum_days)) {
    q.delete("momentum_min");
    q.delete("momentum_max");
  }
  // Phase 6.5 fundamentals, in the API's units.
  if (present(params.pe_max)) q.set("pe_max", params.pe_max);
  if (present(params.dividend_yield_min)) q.set("dividend_yield_min", params.dividend_yield_min);
  if (present(params.mcap_min_bn)) {
    q.set("market_cap_usd_min", String(Number(params.mcap_min_bn) * 1e9));
  }
  if (present(params.roe_min)) q.set("roe_min", params.roe_min);
  if (present(params.de_max)) q.set("debt_to_equity_max", params.de_max);
  const rule = activeRule(params);
  if (rule) {
    q.set("rule", rule);
    q.set("rule_mode", parseRuleMode(params));
  }
  const { sort, dir } = parseScreenerSort(params);
  q.set("sort", API_SORT[sort]);
  q.set("dir", dir);
  q.set("limit", String(pageSize));
  q.set("offset", String((parseScreenerPage(params) - 1) * pageSize));
  return q;
}

/** The saved-screen query: the filters and sort, never the page. */
export function savedScreenQuery(params: ScreenerParams): string {
  return screenerPageHref(params, 1).replace(/^\/screener\??/, "");
}
