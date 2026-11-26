/**
 * Journal entries (A5.5, M10.3), client-safe: types and the labels the
 * entries list and the entry page share.
 *
 * An entry is one round trip, flat to flat, in a paper or imported book or a
 * replay session; partial exits stay in it. Every figure comes from the API,
 * computed on read (net P&L, R, MAE, MFE); nothing here recomputes them.
 */

import type { components } from "@/lib/api/schema";
import { formatR } from "@/lib/chart-events";

export type JournalEntrySummary = components["schemas"]["JournalEntrySummaryOut"];
export type JournalEntry = components["schemas"]["JournalEntryOut"];
export type JournalEntries = components["schemas"]["JournalEntriesOut"];
export type JournalEntryPatch = components["schemas"]["JournalEntryPatch"];
export type JournalExcursion = components["schemas"]["JournalExcursionOut"];
export type JournalNewsWindow = components["schemas"]["JournalNewsWindowOut"];

export { formatR };

export const SOURCE_LABEL: Record<JournalEntrySummary["source"], string> = {
  paper: "Paper",
  imported: "Imported",
  replay: "Replay",
};

export type EntryBadge = { label: string; tone: "locked" | "after" | "none" };

export const BADGE_CLASS: Record<EntryBadge["tone"], string> = {
  locked: "border-brand/40 bg-brand/10 text-foreground",
  after: "border-warning/40 bg-warning-soft text-warning-soft-foreground",
  none: "border-border-muted text-text-tertiary",
};

/** An amount in its currency, two decimals (server and client safe). */
export function money(value: number | string | null | undefined, currency: string): string {
  const v = Number(value);
  if (value === null || value === undefined || !Number.isFinite(v)) return "—";
  try {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency,
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(v);
  } catch {
    return `${currency} ${v.toFixed(2)}`;
  }
}

/** The plan badge: Locked plan, Written after entry, or No plan. */
export function entryPlanBadge(entry: Pick<JournalEntrySummary, "plan">): EntryBadge {
  if (!entry.plan) return { label: "No plan", tone: "none" };
  return entry.plan.label === "locked"
    ? { label: "Locked plan", tone: "locked" }
    : { label: "Written after entry", tone: "after" };
}

/** "+1.25R", or "—" when there is no R (no plan or no stop). */
export function rText(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : formatR(value);
}

/** An excursion as a percent of cost: "-2.50%". */
export function excursionPct(e: JournalExcursion | null | undefined): string {
  if (!e) return "—";
  const v = Number(e.pct);
  return `${v > 0 ? "+" : ""}${v.toFixed(2)}%`;
}

/** The tone of a signed figure: gain, loss or flat. */
export function tone(value: number | string | null | undefined): "gain" | "loss" | "flat" {
  const v = Number(value);
  if (!Number.isFinite(v) || v === 0) return "flat";
  return v > 0 ? "gain" : "loss";
}

export const TONE_CLASS = {
  gain: "text-gain",
  loss: "text-loss",
  flat: "text-text-secondary",
} as const;

/** Tags typed as one comma-separated field. */
export function splitEntryTags(raw: string): string[] {
  return raw
    .split(",")
    .map((t) => t.trim())
    .filter(Boolean);
}

/** The entry page's URL, keeping the book the journal was opened from. */
export function entryHref(id: number, book?: number | "all" | null): string {
  return book ? `/portfolio/journal/${id}?book=${book}` : `/portfolio/journal/${id}`;
}
