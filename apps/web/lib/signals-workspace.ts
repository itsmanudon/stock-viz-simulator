import type { Recommendation, RecommendationVote } from "@/lib/api";

export const SIGNAL_MAX_SCORE = 7;
export const SIGNAL_BULLISH_THRESHOLD = 4;

export const SIGNAL_VOTE_ORDER = [
  "below_mean",
  "below_median",
  "within_one_stdev",
  "volume_above_mean",
  "recent_uptrend",
  "positive_slope",
  "positive_sentiment",
] as const;

export type SignalClass = "bullish" | "neutral";
export type SignalFilter = "all" | SignalClass;
export type SignalSortKey = "score" | "ticker" | "sentiment" | "updated";
export type SignalSortDir = "asc" | "desc";

export type SignalSearchParams = {
  min?: string;
  signal?: string;
  sector?: string;
  q?: string;
  sort?: string;
  dir?: string;
};

export type SignalRow = {
  ticker: string;
  name: string;
  sector: string | null;
  score: number;
  signal: SignalClass;
  votes: RecommendationVote[];
  supportingVotes: number;
  sentiment7d: number | null;
  computedAt: string;
};

export function classifySignal(score: number): SignalClass {
  return score >= SIGNAL_BULLISH_THRESHOLD ? "bullish" : "neutral";
}

export function parseSignalFilter(raw: string | undefined): SignalFilter {
  if (raw === "bullish" || raw === "neutral") return raw;
  return "all";
}

export function parseSignalSort(raw: string | undefined): SignalSortKey {
  if (raw === "ticker" || raw === "sentiment" || raw === "updated") return raw;
  return "score";
}

export function parseSignalSortDir(raw: string | undefined, sort: SignalSortKey): SignalSortDir {
  if (raw === "asc" || raw === "desc") return raw;
  return sort === "ticker" ? "asc" : "desc";
}

export function parseMinScore(raw: string | undefined): number {
  const parsed = Number.parseInt(raw ?? "0", 10);
  if (!Number.isFinite(parsed)) return 0;
  return Math.max(0, Math.min(SIGNAL_MAX_SCORE, parsed));
}

export function recommendationToSignal(rec: Recommendation): SignalRow {
  const votes = rec.votes?.length ? rec.votes : votesFromRationale(rec.rationale ?? []);
  return {
    ticker: rec.ticker,
    name: rec.name,
    sector: rec.sector,
    score: rec.score,
    signal: classifySignal(rec.score),
    votes,
    supportingVotes: votes.filter((vote) => vote.passed).length,
    sentiment7d: rec.sentiment_7d ?? null,
    computedAt: rec.computed_at,
  };
}

export function votesFromRationale(rationale: string[]): RecommendationVote[] {
  const specs: Array<[string, string, string]> = [
    ["below_mean", "Below historical mean", "Below historical mean"],
    ["below_median", "Below historical median", "Below historical median"],
    ["within_one_stdev", "Within 1 stdev below mean", "Within 1 stdev below mean"],
    ["volume_above_mean", "Volume above average", "Volume above average"],
    ["recent_uptrend", "3-bar uptrend", "uptrend"],
    ["positive_slope", "Positive 5-bar slope", "-bar slope"],
    ["positive_sentiment", "Positive news sentiment", "Positive news sentiment"],
  ];
  const remaining = [...rationale];
  return specs.map(([id, label, needle]) => {
    const match = remaining.find((item) => item.toLowerCase().includes(needle.toLowerCase()));
    if (match) {
      remaining.splice(remaining.indexOf(match), 1);
      return { id, label, passed: true, detail: match };
    }
    return {
      id,
      label,
      passed: false,
      detail: `${label} did not contribute to this score`,
    };
  });
}

export function filterSignals(
  rows: SignalRow[],
  {
    signal = "all",
    sector,
    query,
  }: {
    signal?: SignalFilter;
    sector?: string;
    query?: string;
  },
): SignalRow[] {
  const needle = query?.trim().toUpperCase() ?? "";
  return rows.filter((row) => {
    if (signal !== "all" && row.signal !== signal) return false;
    if (sector && row.sector !== sector) return false;
    if (needle && !row.ticker.includes(needle) && !row.name.toUpperCase().includes(needle)) {
      return false;
    }
    return true;
  });
}

export function sortSignals(
  rows: SignalRow[],
  sort: SignalSortKey,
  dir: SignalSortDir,
): SignalRow[] {
  const copy = [...rows];
  copy.sort((a, b) => {
    const direction = dir === "asc" ? 1 : -1;
    switch (sort) {
      case "ticker":
        return a.ticker.localeCompare(b.ticker) * direction;
      case "sentiment": {
        const av = a.sentiment7d;
        const bv = b.sentiment7d;
        if (av === null && bv === null) return a.ticker.localeCompare(b.ticker);
        if (av === null) return 1;
        if (bv === null) return -1;
        return (av - bv) * direction;
      }
      case "updated":
        return a.computedAt.localeCompare(b.computedAt) * direction;
      default:
        if (a.score !== b.score) return (a.score - b.score) * direction;
        return a.ticker.localeCompare(b.ticker);
    }
  });
  return copy;
}

export function buildSignalsHref(params: {
  min?: number;
  signal?: SignalFilter;
  sector?: string;
  q?: string;
  sort?: SignalSortKey;
  dir?: SignalSortDir;
}): string {
  const search = new URLSearchParams();
  if (params.min && params.min > 0) search.set("min", String(params.min));
  if (params.signal && params.signal !== "all") search.set("signal", params.signal);
  if (params.sector) search.set("sector", params.sector);
  if (params.q) search.set("q", params.q);
  if (params.sort && params.sort !== "score") search.set("sort", params.sort);
  if (params.dir && !(params.sort === "score" && params.dir === "desc")) {
    search.set("dir", params.dir);
  }
  const qs = search.toString();
  return qs ? `/recommendations?${qs}` : "/recommendations";
}

export function formatSignalDate(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" });
}
