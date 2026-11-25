import "server-only";

import type { components } from "./schema";
import { authedDelete, authedGet, authedPatch, authedPost } from "./server";

export type WatchlistItem = {
  ticker: string;
  name: string;
  sector: string | null;
  added_at: string;
  last_close: string | null;
  /** Timestamp of the bar behind last_close (audit RS-13). Optional: cached responses may predate it. */
  last_close_at?: string | null;
  /** The symbol's trading currency; last_close is in it. */
  currency?: string;
  /** Phase 6.6 (RS-12): the last 30 closes, oldest first, for the sparkline. */
  closes?: string[];
};

export function listWatchlist(): Promise<WatchlistItem[]> {
  return authedGet<WatchlistItem[]>("/v1/watchlist");
}

export function addToWatchlist(ticker: string): Promise<WatchlistItem> {
  return authedPost<WatchlistItem>(`/v1/watchlist/${encodeURIComponent(ticker)}`);
}

export function removeFromWatchlist(ticker: string): Promise<void> {
  return authedDelete(`/v1/watchlist/${encodeURIComponent(ticker)}`);
}

// ---------------------------------------------------------------------------
// A2.5 (M4.6): many lists, notes, tags, column sets. The routes above act on
// the default list and stay for the stock page's one-click star and the
// dashboard widget.
// ---------------------------------------------------------------------------

export type WatchlistList = components["schemas"]["WatchlistOut"];
export type WatchlistColour = WatchlistList["colour"];
export type WatchlistRow = components["schemas"]["WatchlistRowOut"];
export type WatchlistItems = components["schemas"]["WatchlistItemsOut"];
export type WatchlistBulkResult = components["schemas"]["WatchlistBulkOut"];
export type ColumnSet = components["schemas"]["ColumnSetOut"];
export type ColumnKey = ColumnSet["columns"][number];

/** The caller's lists by position; `contains` asks whether each holds that ticker. */
export function listWatchlists(contains?: string): Promise<WatchlistList[]> {
  const query = contains ? `?contains=${encodeURIComponent(contains)}` : "";
  return authedGet<WatchlistList[]>(`/v1/watchlists${query}`);
}

export function createWatchlist(name: string, colour: WatchlistColour): Promise<WatchlistList> {
  return authedPost<WatchlistList>("/v1/watchlists", { name, colour });
}

export function updateWatchlist(
  id: number,
  fields: {
    name?: string;
    colour?: WatchlistColour;
    is_default?: true;
    column_set_id?: number | null;
  },
): Promise<WatchlistList> {
  return authedPatch<WatchlistList>(`/v1/watchlists/${id}`, fields);
}

export function reorderWatchlists(ids: number[]): Promise<WatchlistList[]> {
  return authedPost<WatchlistList[]>("/v1/watchlists/reorder", { ids });
}

export function deleteWatchlist(id: number): Promise<void> {
  return authedDelete(`/v1/watchlists/${id}`);
}

export function listWatchlistItems(
  id: number,
  options: { columnSetId?: number | null; columns?: ColumnKey[] } = {},
): Promise<WatchlistItems> {
  const params = new URLSearchParams();
  if (options.columns?.length) params.set("columns", options.columns.join(","));
  else if (options.columnSetId != null) params.set("column_set_id", String(options.columnSetId));
  const query = params.toString();
  return authedGet<WatchlistItems>(`/v1/watchlists/${id}/items${query ? `?${query}` : ""}`);
}

export function addWatchlistItems(id: number, tickers: string[]): Promise<WatchlistBulkResult> {
  return authedPost<WatchlistBulkResult>(`/v1/watchlists/${id}/items`, { tickers });
}

export function updateWatchlistItem(
  id: number,
  ticker: string,
  fields: { note?: string | null; tags?: string[] },
): Promise<WatchlistRow> {
  return authedPatch<WatchlistRow>(
    `/v1/watchlists/${id}/items/${encodeURIComponent(ticker)}`,
    fields,
  );
}

export function removeWatchlistItem(id: number, ticker: string): Promise<void> {
  return authedDelete(`/v1/watchlists/${id}/items/${encodeURIComponent(ticker)}`);
}

export function listColumnSets(): Promise<ColumnSet[]> {
  return authedGet<ColumnSet[]>("/v1/column-sets");
}

export function createColumnSet(name: string, columns: ColumnKey[]): Promise<ColumnSet> {
  return authedPost<ColumnSet>("/v1/column-sets", { name, columns });
}

export function updateColumnSet(
  id: number,
  fields: { name?: string; columns?: ColumnKey[] },
): Promise<ColumnSet> {
  return authedPatch<ColumnSet>(`/v1/column-sets/${id}`, fields);
}

export function deleteColumnSet(id: number): Promise<void> {
  return authedDelete(`/v1/column-sets/${id}`);
}
