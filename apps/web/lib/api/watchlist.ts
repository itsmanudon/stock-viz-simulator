import "server-only";

import { authedDelete, authedGet, authedPost } from "./server";

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
