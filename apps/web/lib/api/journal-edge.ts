import "server-only";

/**
 * `/v1/journal/stats` (A5.6, M10.3): "Is my edge real?" over the closed
 * journal entries, private to the user. Types and labels are client-safe in
 * `lib/journal-edge.ts`.
 */

import { type EdgeFilters, type EdgeStats, edgeQuery } from "@/lib/journal-edge";

import { authedGet } from "./server";

/** One book's stats (a numeric book), or every book and replay (null or "all"). */
export function getJournalStats(
  book: number | "all" | null,
  filters: EdgeFilters = {},
): Promise<EdgeStats> {
  const query = edgeQuery(book, filters);
  return authedGet<EdgeStats>(`/v1/journal/stats${query ? `?${query}` : ""}`);
}
