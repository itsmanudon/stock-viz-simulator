import "server-only";

import { authedDelete, authedGet, authedPost } from "./server";

export type WatchlistItem = {
  ticker: string;
  name: string;
  sector: string | null;
  added_at: string;
  last_close: string | null;
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
