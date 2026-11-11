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
] as const satisfies readonly (keyof ScreenerParams)[];

export type ScreenerSortKey = "ticker" | "price" | "rsi" | "momentum";
export type SortDir = "asc" | "desc";

export type FilterChip = { id: string; label: string; removeHref: string };

function present(value: string | undefined): value is string {
  return value !== undefined && value !== "" && Number.isFinite(Number(value));
}

function href(params: ScreenerParams, drop: readonly (keyof ScreenerParams)[] = []): string {
  const next = new URLSearchParams();
  for (const key of PARAM_KEYS) {
    const value = params[key];
    if (value && !drop.includes(key)) next.set(key, value);
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
  const keys: ScreenerSortKey[] = ["ticker", "price", "rsi"];
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
