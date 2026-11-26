/**
 * Pure helpers for the news page (news redesign, 26 Nov 2026): URL state,
 * story grouping, day groups and the small geometry the timeline and the
 * reaction sparklines draw. Client-safe; no API calls.
 *
 * Everything here works from what Aegis sends: headline, source, dates,
 * links, linked tickers, sentiment and topic labels. There is no article
 * text, so stories group by headline words, never by content.
 */

import type { NewsFeedItem } from "@/lib/api/news";

export const NEWS_SENTIMENTS = ["positive", "neutral", "negative", "mixed", "unscored"] as const;
export type NewsSentiment = (typeof NEWS_SENTIMENTS)[number];
export type NewsScope = "symbols" | "market" | "all";

export type NewsQuery = {
  q: string;
  tickers: string[];
  sentiment: NewsSentiment[];
  topic: string[];
  source: string[];
  scope: NewsScope;
  from: string | null;
  to: string | null;
  cursor: string | null;
  /** "mine": holdings and watchlist, resolved to tickers by the page. */
  lens: "all" | "mine";
};

type RawParams = Record<string, string | string[] | undefined>;

function first(raw: string | string[] | undefined): string {
  return (Array.isArray(raw) ? raw[0] : raw) ?? "";
}

function list(raw: string | string[] | undefined): string[] {
  const values = (Array.isArray(raw) ? raw : [raw ?? ""])
    .flatMap((v) => v.split(","))
    .map((v) => v.trim())
    .filter(Boolean);
  return [...new Set(values)];
}

const DATE = /^\d{4}-\d{2}-\d{2}$/;

export function parseNewsQuery(params: RawParams): NewsQuery {
  // `?view=market` is the old page's market view; old links still open it.
  const scope = first(params.scope) || (first(params.view) === "market" ? "market" : "");
  const from = first(params.from);
  const to = first(params.to);
  return {
    q: first(params.q).trim().slice(0, 200),
    tickers: [...new Set(list(params.tickers).map((t) => t.toUpperCase()))].slice(0, 50),
    sentiment: list(params.sentiment).filter((s): s is NewsSentiment =>
      (NEWS_SENTIMENTS as readonly string[]).includes(s),
    ),
    topic: list(params.topic).slice(0, 20),
    source: list(params.source).slice(0, 20),
    scope: scope === "market" || scope === "all" ? scope : "symbols",
    from: DATE.test(from) ? from : null,
    to: DATE.test(to) ? to : null,
    cursor: first(params.cursor) || null,
    lens: first(params.lens) === "mine" ? "mine" : "all",
  };
}

/** The page URL for `query` with `patch` applied; paging resets unless the patch sets it. */
export function newsHref(query: NewsQuery, patch: Partial<NewsQuery> = {}): string {
  const next: NewsQuery = { ...query, cursor: null, ...patch };
  const params = new URLSearchParams();
  if (next.q) params.set("q", next.q);
  if (next.lens === "mine") params.set("lens", "mine");
  else if (next.tickers.length) params.set("tickers", next.tickers.join(","));
  if (next.sentiment.length) params.set("sentiment", next.sentiment.join(","));
  if (next.topic.length) params.set("topic", next.topic.join(","));
  if (next.source.length) params.set("source", next.source.join(","));
  if (next.scope !== "symbols") params.set("scope", next.scope);
  if (next.from) params.set("from", next.from);
  if (next.to) params.set("to", next.to);
  if (next.cursor) params.set("cursor", next.cursor);
  const qs = params.toString();
  return qs ? `/news?${qs}` : "/news";
}

/** Toggle one value in a list filter (a chip). */
export function toggled<T extends string>(values: readonly T[], value: T): T[] {
  return values.includes(value) ? values.filter((v) => v !== value) : [...values, value];
}

/** The API's query for `query`, with the lens already resolved to `tickers`. */
export function newsApiParams(query: NewsQuery, tickers: string[], limit = 40): URLSearchParams {
  const params = new URLSearchParams();
  if (query.q) params.set("q", query.q);
  if (tickers.length) params.set("tickers", tickers.join(","));
  if (query.sentiment.length) params.set("sentiment", query.sentiment.join(","));
  if (query.topic.length) params.set("topic", query.topic.join(","));
  if (query.source.length) params.set("source", query.source.join(","));
  // A personal lens reads the symbols' news; market headlines have no ticker.
  params.set("scope", tickers.length && query.scope === "market" ? "symbols" : query.scope);
  if (query.from) params.set("from", query.from);
  if (query.to) params.set("to", query.to);
  if (query.cursor) params.set("cursor", query.cursor);
  params.set("limit", String(limit));
  return params;
}

export function activeFilterCount(query: NewsQuery): number {
  return (
    (query.q ? 1 : 0) +
    (query.lens === "mine" ? 1 : query.tickers.length ? 1 : 0) +
    (query.sentiment.length ? 1 : 0) +
    (query.topic.length ? 1 : 0) +
    (query.source.length ? 1 : 0) +
    (query.from || query.to ? 1 : 0)
  );
}

// ---------------------------------------------------------------------------
// Stories: the same event from several outlets
// ---------------------------------------------------------------------------

const STOPWORDS = new Set(
  "a an and are as at be by for from has have in into is it its of on or over says say the their to up was were will with after amid as but not new more than shares stock stocks inc corp ltd".split(
    " ",
  ),
);

/** Lower-case headline words of 3+ letters, stopwords and tickers' noise removed. */
export function headlineWords(title: string): Set<string> {
  const words = title
    .toLowerCase()
    .replace(/[^a-z0-9\s]/g, " ")
    .split(/\s+/)
    .filter((w) => w.length > 2 && !STOPWORDS.has(w));
  return new Set(words);
}

export function similarity(a: Set<string>, b: Set<string>): number {
  if (a.size === 0 || b.size === 0) return 0;
  let shared = 0;
  for (const w of a) if (b.has(w)) shared += 1;
  return shared / (a.size + b.size - shared);
}

/** Headlines at least this similar (Jaccard on words) are one story. */
export const STORY_THRESHOLD = 0.45;

export type NewsStory = {
  lead: NewsFeedItem;
  /** The same story from other outlets, newest first. */
  others: NewsFeedItem[];
};

export function dayOf(item: Pick<NewsFeedItem, "available_at">): string {
  return item.available_at.slice(0, 10);
}

/**
 * Group a page of headlines into stories: same UTC day, same linked tickers,
 * and similar headline words. The newest headline leads; order is kept.
 */
export function groupStories(items: readonly NewsFeedItem[]): NewsStory[] {
  const stories: { story: NewsStory; key: string; words: Set<string> }[] = [];
  for (const item of items) {
    const key = `${dayOf(item)}|${[...item.tickers].sort().join(",")}`;
    const words = headlineWords(item.title);
    const match = stories.find(
      (s) => s.key === key && similarity(s.words, words) >= STORY_THRESHOLD,
    );
    if (match) match.story.others.push(item);
    else stories.push({ story: { lead: item, others: [] }, key, words });
  }
  return stories.map((s) => s.story);
}

export type NewsDayGroup = {
  date: string;
  stories: NewsStory[];
  tone: Record<NewsSentiment, number>;
};

/** Stories by UTC day of `available_at`, with each day's tone counts (every headline). */
export function groupByDay(stories: readonly NewsStory[]): NewsDayGroup[] {
  const days: NewsDayGroup[] = [];
  for (const story of stories) {
    const date = dayOf(story.lead);
    let day = days.at(-1);
    if (!day || day.date !== date) {
      day = {
        date,
        stories: [],
        tone: { positive: 0, neutral: 0, negative: 0, mixed: 0, unscored: 0 },
      };
      days.push(day);
    }
    day.stories.push(story);
    for (const item of [story.lead, ...story.others]) {
      day.tone[(item.sentiment ?? "unscored") as NewsSentiment] += 1;
    }
  }
  return days;
}

// ---------------------------------------------------------------------------
// Geometry
// ---------------------------------------------------------------------------

/** SVG path through `values` in a `width` x `height` box with `pad` inside. */
export function sparkPath(
  values: readonly number[],
  width: number,
  height: number,
  pad = 2,
): string {
  if (values.length < 2) return "";
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const step = (width - pad * 2) / (values.length - 1);
  return values
    .map((v, i) => {
      const x = pad + i * step;
      const y = pad + (1 - (v - min) / span) * (height - pad * 2);
      return `${i ? "L" : "M"}${x.toFixed(1)} ${y.toFixed(1)}`;
    })
    .join(" ");
}

/** Where `values[index]` sits in the same box, for the reaction dot. */
export function sparkPoint(
  values: readonly number[],
  index: number,
  width: number,
  height: number,
  pad = 2,
): { x: number; y: number } | null {
  if (values.length < 2 || index < 0 || index >= values.length) return null;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const step = (width - pad * 2) / (values.length - 1);
  return {
    x: pad + index * step,
    y: pad + (1 - (values[index] - min) / span) * (height - pad * 2),
  };
}

/** "+1.24%" / "−3.10%" with a real minus sign, or "—" without a figure. */
export function signedPct(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "—";
  const sign = value > 0 ? "+" : value < 0 ? "−" : "";
  return `${sign}${Math.abs(value).toFixed(2)}%`;
}

/** Day index (0-based) of an ISO date inside `days`, for the brush. */
export function dayIndex(days: readonly { date: string }[], date: string | null): number | null {
  if (!date) return null;
  const i = days.findIndex((d) => d.date >= date);
  return i < 0 ? null : i;
}
