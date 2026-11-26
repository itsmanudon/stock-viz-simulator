import { apiGet } from "./client";
import type { components } from "./schema";
import type { NewsArticle } from "./types";

// News is copied from Aegis once a night, so a 15-minute cache is well inside
// the refresh window and takes the repeat load off the origin.
const NEWS_REVALIDATE_SECONDS = 900;

export function getLatestNews(limit = 50): Promise<NewsArticle[]> {
  return apiGet<NewsArticle[]>(`/v1/news?limit=${limit}`, {
    revalidateSeconds: NEWS_REVALIDATE_SECONDS,
    tags: ["news"],
  });
}

/**
 * General market headlines: stored documents linked to no StockViz symbol
 * (rates, indices, companies StockViz does not list). Shown in their own
 * section, never as news about a symbol.
 */
export function getMarketNews(limit = 50): Promise<NewsArticle[]> {
  return apiGet<NewsArticle[]>(`/v1/news?scope=market&limit=${limit}`, {
    revalidateSeconds: NEWS_REVALIDATE_SECONDS,
    tags: ["news"],
  });
}

export function getNewsForTicker(ticker: string, limit = 20): Promise<NewsArticle[]> {
  return apiGet<NewsArticle[]>(`/v1/symbols/${encodeURIComponent(ticker)}/news?limit=${limit}`, {
    revalidateSeconds: NEWS_REVALIDATE_SECONDS,
    tags: ["news"],
  });
}

/**
 * News linked to any of `tickers`, newest first: a watchlist or a portfolio's
 * holdings. A document linked to several of them appears once. Tickers are
 * sorted so the same set always hits the same cache entry.
 */
export function getNewsForTickers(tickers: string[], limit = 20): Promise<NewsArticle[]> {
  const unique = [...new Set(tickers.map((t) => t.trim().toUpperCase()).filter(Boolean))].sort();
  if (unique.length === 0) return Promise.resolve([]);
  const query = encodeURIComponent(unique.join(","));
  return apiGet<NewsArticle[]>(`/v1/news?tickers=${query}&limit=${limit}`, {
    revalidateSeconds: NEWS_REVALIDATE_SECONDS,
    tags: ["news"],
  });
}

// ---------------------------------------------------------------------------
// The news page's archive (news redesign, 26 Nov 2026): `/v1/news/feed` and
// `/v1/news/overview`. Types come from the API schema.
// ---------------------------------------------------------------------------

export type NewsFeed = components["schemas"]["NewsFeedOut"];
export type NewsFeedItem = components["schemas"]["NewsFeedItemOut"];
export type NewsReaction = components["schemas"]["NewsReactionOut"];
export type NewsOverview = components["schemas"]["NewsOverviewOut"];
export type NewsDay = components["schemas"]["NewsDayOut"];
export type NewsHeatRow = components["schemas"]["NewsHeatRowOut"];

/** `params` is built by `newsApiParams()` (lib/news-view.ts). */
export function getNewsFeed(params: URLSearchParams): Promise<NewsFeed> {
  return apiGet<NewsFeed>(`/v1/news/feed?${params.toString()}`, {
    revalidateSeconds: NEWS_REVALIDATE_SECONDS,
    tags: ["news", "bars"],
  });
}

export function getNewsOverview(params: URLSearchParams): Promise<NewsOverview> {
  const query = new URLSearchParams(params);
  query.delete("cursor");
  query.delete("limit");
  return apiGet<NewsOverview>(`/v1/news/overview?${query.toString()}`, {
    revalidateSeconds: NEWS_REVALIDATE_SECONDS,
    tags: ["news"],
  });
}
