import { apiGet } from "./client";
import type { Recommendation } from "./types";

export type RecommendationsParams = {
  minScore?: number;
  limit?: number;
};

export function getRecommendations(params: RecommendationsParams = {}): Promise<Recommendation[]> {
  const q = new URLSearchParams();
  if (params.minScore !== undefined) q.set("min_score", String(params.minScore));
  if (params.limit !== undefined) q.set("limit", String(params.limit));
  const qs = q.toString();
  return apiGet<Recommendation[]>(`/v1/recommendations${qs ? `?${qs}` : ""}`).then((rows) =>
    rows.map((row) => ({
      ...row,
      votes: row.votes ?? [],
      sentiment_7d: row.sentiment_7d ?? null,
    })),
  );
}
