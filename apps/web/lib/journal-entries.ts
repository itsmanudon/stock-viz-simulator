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

export type MarkerSide = "aboveBar" | "belowBar";

/** Where the chart draws one excursion (A5 fix): its side of the bar, or folded into a fill. */
export type ExcursionPlacement = {
  kind: "mae" | "mfe";
  date: string;
  position: MarkerSide;
  /** Both sides of the bar already hold a marker: the label joins the fill's ("S · MAE -0.41%"). */
  mergeIntoFill: boolean;
};

const OTHER: Record<MarkerSide, MarkerSide> = { aboveBar: "belowBar", belowBar: "aboveBar" };

/**
 * Where MAE and MFE go so they never stack on a fill marker (a stack runs off
 * the pane and clips the fill's letter, on desktop and phone alike).
 *
 * Fill markers keep their side: buys below the bar, sells above. An
 * excursion prefers the side of the extreme it measures: for a long entry
 * MAE below (the low) and MFE above (the high); for a short entry the other
 * way round (adverse = the price going up). On a bar where that side already
 * holds a fill or the other excursion, it moves to the other side when that
 * is free; when both sides are taken (an intraday round trip: a buy and a
 * sell on one bar), its label joins the fill's on its preferred side, or on
 * the other side if only that one holds a fill.
 */
export function placeExcursionMarkers(
  entry: Pick<JournalEntry, "excursions" | "fills"> & { side?: JournalEntry["side"] },
): ExcursionPlacement[] {
  const short = entry.side === "short";
  const fillSides = new Map<string, Set<MarkerSide>>();
  for (const f of entry.fills) {
    const set = fillSides.get(f.venue_date) ?? new Set<MarkerSide>();
    set.add(f.side === "sell" ? "aboveBar" : "belowBar");
    fillSides.set(f.venue_date, set);
  }
  const placed = new Map<string, Set<MarkerSide>>();
  const out: ExcursionPlacement[] = [];
  const items: [ExcursionPlacement["kind"], JournalExcursion | null | undefined, MarkerSide][] = [
    ["mae", entry.excursions.mae, short ? "aboveBar" : "belowBar"],
    ["mfe", entry.excursions.mfe, short ? "belowBar" : "aboveBar"],
  ];
  for (const [kind, e, preferred] of items) {
    if (!e) continue;
    const fills = fillSides.get(e.date) ?? new Set<MarkerSide>();
    const mine = placed.get(e.date) ?? new Set<MarkerSide>();
    const free = (side: MarkerSide) => !fills.has(side) && !mine.has(side);
    let position = preferred;
    let mergeIntoFill = false;
    if (!free(preferred)) {
      if (free(OTHER[preferred])) {
        position = OTHER[preferred];
      } else {
        position = fills.has(preferred) ? preferred : OTHER[preferred];
        mergeIntoFill = true;
      }
    }
    if (!mergeIntoFill) {
      mine.add(position);
      placed.set(e.date, mine);
    }
    out.push({ kind, date: e.date, position, mergeIntoFill });
  }
  return out;
}
