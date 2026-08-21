import { apiGet } from "./client";
import type { NewsArticle } from "./types";

// News is ingested every four hours, so a 15-minute cache is well inside the
// refresh window and takes the repeat load off the origin.
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
