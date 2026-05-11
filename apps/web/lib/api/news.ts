import { apiGet } from "./client";
import type { NewsArticle } from "./types";

export function getLatestNews(limit = 50): Promise<NewsArticle[]> {
  return apiGet<NewsArticle[]>(`/v1/news?limit=${limit}`);
}

export function getNewsForTicker(ticker: string, limit = 20): Promise<NewsArticle[]> {
  return apiGet<NewsArticle[]>(`/v1/symbols/${encodeURIComponent(ticker)}/news?limit=${limit}`);
}
