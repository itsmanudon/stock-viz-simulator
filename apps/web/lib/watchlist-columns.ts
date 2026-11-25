/**
 * Watchlist columns and colour tags (A2.5, M4.6). Pure and client-safe.
 *
 * `COLUMN_META` covers every key of the API's allow-list
 * (`services/watchlists.COLUMN_KEYS`); `tests/unit/watchlists.test.tsx`
 * checks the two agree through the generated schema type. A value the API
 * sends as null renders as an em dash, never 0.
 */

import type { components } from "@/lib/api/schema";
import { formatCurrency, formatSignedPercent } from "@/lib/portfolio-view-model";

export type ColumnKey = components["schemas"]["ColumnSetOut"]["columns"][number];
export type WatchlistColour = components["schemas"]["WatchlistOut"]["colour"];
type Values = Record<string, number | string | null | undefined>;

type Kind =
  | "price"
  | "signed"
  | "number"
  | "percent"
  | "ratio"
  | "usd"
  | "volume"
  | "checklist"
  | "text";

export const COLUMN_META: Record<ColumnKey, { label: string; kind: Kind; hint: string }> = {
  close: { label: "Last close", kind: "price", hint: "Latest stored daily close" },
  change_pct: { label: "Day change", kind: "signed", hint: "Last close against the one before" },
  rsi_14: { label: "RSI(14)", kind: "number", hint: "14-session RSI" },
  pct_from_52w_high: {
    label: "From 52w high",
    kind: "signed",
    hint: "Close against the 52-week high",
  },
  sma_50_gap_pct: { label: "vs 50-day", kind: "signed", hint: "Close against the 50-day average" },
  sma_200_gap_pct: {
    label: "vs 200-day",
    kind: "signed",
    hint: "Close against the 200-day average",
  },
  atr_pct_14: { label: "ATR %", kind: "percent", hint: "ATR(14) as a percent of the close" },
  hv_20: { label: "Volatility", kind: "percent", hint: "20-day historical volatility, annualised" },
  volume_ratio: {
    label: "Volume ratio",
    kind: "ratio",
    hint: "Latest volume over the 20-day average",
  },
  avg_volume_20: { label: "Avg volume", kind: "volume", hint: "20-day average volume" },
  pe: { label: "P/E", kind: "number", hint: "Price to earnings, as known on the latest close" },
  pb: { label: "P/B", kind: "number", hint: "Price to book" },
  market_cap_usd: { label: "Mkt cap (USD)", kind: "usd", hint: "Market capitalisation in USD" },
  dividend_yield: { label: "Div. yield", kind: "percent", hint: "Dividend yield" },
  roe: { label: "ROE", kind: "percent", hint: "Return on equity" },
  sentiment_7d: {
    label: "News 7d",
    kind: "number",
    hint: "Mean Aegis News sentiment, last week (-1 to 1)",
  },
  delivery_pct: { label: "Delivery %", kind: "percent", hint: "NSE delivery share of volume" },
  checklist_met: { label: "Checklist", kind: "checklist", hint: "Checklist conditions met" },
  sector: { label: "Sector", kind: "text", hint: "Sector from symbol metadata" },
};

export const COLUMN_KEYS = Object.keys(COLUMN_META) as ColumnKey[];

/** What a list shows when it has no column set (the API's DEFAULT_COLUMNS). */
export const DEFAULT_COLUMNS: ColumnKey[] = [
  "close",
  "change_pct",
  "rsi_14",
  "pct_from_52w_high",
  "sector",
];

const COMPACT = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 2 });

function numeric(raw: number | string | null | undefined): number | null {
  if (raw === null || raw === undefined || raw === "") return null;
  const value = typeof raw === "number" ? raw : Number(raw);
  return Number.isFinite(value) ? value : null;
}

/** A column's value as text, in the symbol's currency for prices. */
export function formatColumnValue(key: ColumnKey, values: Values, currency = "USD"): string {
  const meta = COLUMN_META[key];
  const raw = values[key];
  if (meta.kind === "text") return typeof raw === "string" && raw ? raw : "—";
  const value = numeric(raw);
  if (value === null) return "—";
  switch (meta.kind) {
    case "price":
      return formatCurrency(value, currency);
    case "signed":
      return formatSignedPercent(value);
    case "percent":
      return `${value.toFixed(1)}%`;
    case "ratio":
      return `${value.toFixed(2)}×`;
    case "usd":
      return `$${COMPACT.format(value)}`;
    case "volume":
      return COMPACT.format(value);
    case "checklist": {
      const of = numeric(values.checklist_evaluated);
      return of === null ? String(value) : `${value} of ${of}`;
    }
    default:
      return value.toFixed(key === "sentiment_7d" ? 2 : 1);
  }
}

/** Signed columns tint by sign; the rest stay neutral. */
export function columnSign(key: ColumnKey, values: Values): number | null {
  if (COLUMN_META[key].kind !== "signed") return null;
  return numeric(values[key]);
}

export const LIST_COLOURS: { key: WatchlistColour; label: string }[] = [
  { key: "aqua", label: "Aqua" },
  { key: "blue", label: "Blue" },
  { key: "violet", label: "Violet" },
  { key: "pink", label: "Pink" },
  { key: "amber", label: "Amber" },
  { key: "lime", label: "Lime" },
  { key: "slate", label: "Slate" },
];

/** The Aurora list token behind a colour tag (`--list-<name>` in globals.css). */
export function listColourVar(colour: string): string {
  return `var(--list-${LIST_COLOURS.some((c) => c.key === colour) ? colour : "aqua"})`;
}

/** Every tag on a list's rows, sorted, each once (case kept from its first use). */
export function tagsOf(rows: { tags?: string[] }[]): string[] {
  const seen = new Map<string, string>();
  for (const row of rows) {
    for (const tag of row.tags ?? []) {
      const key = tag.toLocaleLowerCase();
      if (!seen.has(key)) seen.set(key, tag);
    }
  }
  return [...seen.values()].sort((a, b) => a.localeCompare(b));
}

export function hasTag(row: { tags?: string[] }, tag: string): boolean {
  const wanted = tag.toLocaleLowerCase();
  return (row.tags ?? []).some((t) => t.toLocaleLowerCase() === wanted);
}

/** The new order of list ids after moving one a step left (-1) or right (+1). */
export function moveListId(ids: number[], id: number, step: -1 | 1): number[] {
  const from = ids.indexOf(id);
  const to = from + step;
  if (from < 0 || to < 0 || to >= ids.length) return ids;
  const next = [...ids];
  [next[from], next[to]] = [next[to], next[from]];
  return next;
}

/** Tags typed as text: split on commas, trimmed, empty dropped. */
export function parseTagInput(raw: string): string[] {
  return raw
    .split(",")
    .map((t) => t.trim().replace(/\s+/g, " "))
    .filter(Boolean);
}
