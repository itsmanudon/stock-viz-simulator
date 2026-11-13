import { apiGet } from "./client";

/** Phase 7.4: abnormal returns around news of a kind. Association, not cause. */
export type EventStudyWindow = {
  start: number;
  end: number;
  mean_car_pct: number | null;
  std_error_pct: number | null;
  t_stat: number | null;
};

export type EventStudy = {
  tickers: string[];
  sentiment: string | null;
  event_type: string | null;
  pre: number;
  post: number;
  model: string;
  benchmarks: Record<string, string>;
  no_benchmark: string[];
  min_events: number;
  enough: boolean;
  events_found: number;
  events_used: number;
  events_incomplete: number;
  overlapping: number;
  windows: EventStudyWindow[];
  path: { offset: number; mean_car_pct: number | null; std_error_pct: number | null }[];
  events: {
    ticker: string;
    document_id: string;
    title: string;
    available_at: string;
    event_date: string;
    car_pct: number;
  }[];
};

export type EventStudyParams = {
  tickers: string[];
  sentiment?: string;
  eventType?: string;
  pre?: number;
  post?: number;
};

/**
 * Cached until the nightly revalidation (RS-9): bars and news both change
 * only then.
 */
export function getEventStudy(params: EventStudyParams): Promise<EventStudy> {
  const q = new URLSearchParams();
  for (const t of params.tickers) q.append("tickers", t);
  if (params.sentiment) q.set("sentiment", params.sentiment);
  if (params.eventType) q.set("event_type", params.eventType);
  if (params.pre) q.set("pre", String(params.pre));
  if (params.post) q.set("post", String(params.post));
  return apiGet<EventStudy>(`/v1/research/event-study?${q.toString()}`, {
    revalidateSeconds: 3600,
    tags: ["bars", "news"],
  });
}
