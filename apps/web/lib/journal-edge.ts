/**
 * "Is my edge real?" (A5.6, M10.3 stats), client-safe: types and labels for
 * `/v1/journal/stats`. Every figure (expectancy, intervals, drift) comes from
 * the API, computed on read; nothing here recomputes them.
 */

import type { components } from "@/lib/api/schema";
import { formatR } from "@/lib/chart-events";

export type EdgeStats = components["schemas"]["EdgeStatsOut"];
export type EdgeGroup = components["schemas"]["EdgeGroupOut"];
export type EdgeDrift = components["schemas"]["EdgeDriftOut"];
export type EdgeInterval = components["schemas"]["EdgeIntervalOut"];
export type EdgeSource = NonNullable<EdgeStats["source"]>;

export type EdgeFilters = {
  source?: EdgeSource;
  tag?: string;
  setupVersionId?: number;
  from?: string;
  to?: string;
};

export const SOURCE_OPTIONS: { value: EdgeSource | "live"; label: string }[] = [
  { value: "live", label: "Paper and Imported" },
  { value: "paper", label: "Paper" },
  { value: "imported", label: "Imported" },
  { value: "replay", label: "Replay" },
  { value: "all", label: "All Sources" },
];

export const DRIFT_LABEL: Record<EdgeDrift["status"], string> = {
  consistent: "Consistent",
  outside_interval: "Outside the Interval",
  too_few_live_trades: "Too Few Live Trades",
  too_few_backtest_trades: "Too Few Backtest Trades",
  no_backtest: "No Backtest",
  backtest_no_r: "Backtest Has No R",
};

/** Neutral for every state but "outside", which is flagged in the warning tone, never gain or loss. */
export const DRIFT_CLASS: Record<EdgeDrift["status"], string> = {
  consistent: "border-border-strong text-foreground",
  outside_interval: "border-warning/40 bg-warning-soft text-warning-soft-foreground",
  too_few_live_trades: "border-border-muted text-text-tertiary",
  too_few_backtest_trades: "border-border-muted text-text-tertiary",
  no_backtest: "border-border-muted text-text-tertiary",
  backtest_no_r: "border-border-muted text-text-tertiary",
};

export const KIND_LABEL: Record<EdgeGroup["kind"], string> = {
  overall: "Overall",
  setup: "Setup",
  setup_tag: "Setup Tag",
  mistake_tag: "Mistake Tag",
  source: "Source",
};

function finite(value: number | null | undefined): value is number {
  return value !== null && value !== undefined && Number.isFinite(value);
}

/** A share as a percent: 0.6 -> "60.0%". */
export function pct(value: number | null | undefined, digits = 1): string {
  return finite(value) ? `${(value * 100).toFixed(digits)}%` : "—";
}

export function ratio(value: number | null | undefined): string {
  return finite(value) ? value.toFixed(2) : "—";
}

export function days(value: number | null | undefined): string {
  return finite(value) ? `${value.toFixed(1)} days` : "—";
}

/** Rounds to two places first, so -0.002 reads "+0.00R", never "-0.00R". */
function r2(value: number): number {
  const v = Math.round(value * 100) / 100;
  return Object.is(v, -0) ? 0 : v;
}

export function rValue(value: number | null | undefined): string {
  return finite(value) ? formatR(r2(value)) : "—";
}

/** A money amount in the group's currency (or "—" when money is not shown). */
export function edgeMoney(value: number | null | undefined, currency: string | null | undefined) {
  if (!finite(value) || !currency) return "—";
  try {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency,
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(value);
  } catch {
    return `${currency} ${value.toFixed(2)}`;
  }
}

/** "+0.12R to +0.68R", or "—". */
export function rInterval(interval: EdgeInterval | null | undefined): string {
  if (!interval) return "—";
  return `${formatR(r2(interval.low))} to ${formatR(r2(interval.high))}`;
}

export function moneyInterval(
  interval: EdgeInterval | null | undefined,
  currency: string | null | undefined,
): string {
  if (!interval || !currency) return "—";
  return `${edgeMoney(interval.low, currency)} to ${edgeMoney(interval.high, currency)}`;
}

/** The stats page's URL with these filters and the book. */
export function edgeHref(book: number | "all" | null | undefined, filters: EdgeFilters = {}) {
  const params = new URLSearchParams();
  if (book) params.set("book", String(book));
  if (filters.source) params.set("source", filters.source);
  if (filters.tag) params.set("tag", filters.tag);
  if (filters.setupVersionId) params.set("setup", String(filters.setupVersionId));
  if (filters.from) params.set("from", filters.from);
  if (filters.to) params.set("to", filters.to);
  const query = params.toString();
  return query ? `/portfolio/journal/edge?${query}` : "/portfolio/journal/edge";
}

/** The query string the API takes. */
export function edgeQuery(book: number | "all" | null, filters: EdgeFilters = {}): string {
  const params = new URLSearchParams();
  if (typeof book === "number") params.set("book", String(book));
  if (filters.source) params.set("source", filters.source);
  if (filters.tag) params.set("tag", filters.tag);
  if (filters.setupVersionId) params.set("setup_version_id", String(filters.setupVersionId));
  if (filters.from) params.set("from", filters.from);
  if (filters.to) params.set("to", filters.to);
  return params.toString();
}
