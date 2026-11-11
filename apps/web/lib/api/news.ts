import { apiGet } from "./client";
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
