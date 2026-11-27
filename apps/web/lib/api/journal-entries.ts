import "server-only";

/**
 * `/v1/journal/entries` (A5.5, M10.3): round trips across paper, imported and
 * replay books, private to the user. Types and labels are client-safe in
 * `lib/journal-entries.ts`.
 */

import type { JournalEntries, JournalEntry, JournalEntryPatch } from "@/lib/journal-entries";

import { authedGet, authedPatch } from "./server";

export type JournalEntryFilters = {
  status?: "open" | "closed";
  source?: "paper" | "imported" | "replay";
  tag?: string;
  limit?: number;
};

/** One book's entries (a numeric book), or every entry (null or "all", replay included). */
export function listJournalEntries(
  book: number | "all" | null,
  filters: JournalEntryFilters = {},
): Promise<JournalEntries> {
  const params = new URLSearchParams();
  if (typeof book === "number") params.set("book", String(book));
  if (filters.status) params.set("status", filters.status);
  if (filters.source) params.set("source", filters.source);
  if (filters.tag) params.set("tag", filters.tag);
  params.set("limit", String(filters.limit ?? 100));
  return authedGet<JournalEntries>(`/v1/journal/entries?${params.toString()}`);
}

export function getJournalEntry(id: number): Promise<JournalEntry> {
  return authedGet<JournalEntry>(`/v1/journal/entries/${id}`);
}

export function patchJournalEntry(id: number, body: JournalEntryPatch): Promise<JournalEntry> {
  return authedPatch<JournalEntry>(`/v1/journal/entries/${id}`, body);
}

/** A6.10 (M9.5): "Replay my trade", a read-only playback of a paper or imported entry. */
export type TradeReplay = {
  entry_id: number;
  ticker: string | null;
  currency: string;
  side: "long" | "short";
  status: "open" | "closed";
  interval: "1m" | "1d";
  bars_note: string;
  bars: { ts: string; open: string; high: string; low: string; close: string; volume: number }[];
  fills: {
    at: string;
    side: "buy" | "sell";
    quantity: string;
    price: string;
    time_known: boolean;
  }[];
  planned_entry: string | null;
  planned_stop: string | null;
  planned_target: string | null;
  excursions: JournalEntry["excursions"];
  hesitation: {
    entry_touched_at: string | null;
    fill_at: string;
    wait_bars: number | null;
    stop_breached_at: string | null;
    stop_honoured: boolean | null;
    exit_at: string | null;
    exit_price: string | null;
    note: string;
  } | null;
};

export function getTradeReplay(id: number): Promise<TradeReplay> {
  return authedGet<TradeReplay>(`/v1/journal/entries/${id}/replay`);
}
