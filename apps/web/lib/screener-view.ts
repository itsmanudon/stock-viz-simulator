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
};

const PARAM_KEYS = [
  "market",
  "currency",
  "above_sma_50",
  "above_sma_200",
  "hv_max",
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
] as const satisfies readonly (keyof ScreenerParams)[];

export type ScreenerSortKey = "ticker" | "price" | "rsi" | "momentum" | "trend" | "volatility";

/** The API's sort column for each sortable column (Phase 6.2, sorted server-side). */
export const API_SORT: Record<ScreenerSortKey, string> = {
  ticker: "ticker",
  price: "last_close",
  rsi: "rsi_14",
  momentum: "momentum_pct",
  trend: "sma_200_gap_pct",
  volatility: "hv_20",
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
  return chips;
}

/** Clears every filter but keeps the sort. */
export function clearFiltersHref(params: ScreenerParams): string {
  return href({ sort: params.sort, dir: params.dir });
}

/** The sort the URL asks for, falling back to ticker A-Z when it is invalid. */
export function parseScreenerSort(params: ScreenerParams): {
  sort: ScreenerSortKey;
  dir: SortDir;
} {
  const keys: ScreenerSortKey[] = ["ticker", "price", "rsi", "trend", "volatility"];
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
