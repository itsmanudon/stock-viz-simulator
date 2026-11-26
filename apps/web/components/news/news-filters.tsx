/**
 * NewsFilters: the news page's controls (news redesign, 26 Nov 2026). Server
 * component, URL state only (`lib/news-view.ts`):
 *
 * - a GET form with the headline search (`#news-q`, "/" focuses it) and the
 *   From/To dates (the keyboard path for the timeline's brush);
 * - views: listed companies (default), market headlines, everything, and
 *   "For you" (holdings and watchlist, signed in);
 * - tone, topic and source chips that toggle as links, with counts from the
 *   overview; active ticker and date filters as removable chips.
 */

import { Search, X } from "lucide-react";
import Link from "next/link";

import { NewsSearchShortcut } from "@/components/news/news-search-shortcut";
import type { NewsOverview } from "@/lib/api/news";
import {
  NEWS_SENTIMENTS,
  type NewsQuery,
  type NewsScope,
  activeFilterCount,
  newsHref,
  toggled,
} from "@/lib/news-view";
import { formatCloseDate } from "@/lib/stock-workspace";
import { titleCase } from "@/lib/title-case";
import { cn } from "@/lib/utils";

const VIEWS: { label: string; patch: Partial<NewsQuery>; current: (q: NewsQuery) => boolean }[] = [
  {
    label: "Listed Companies",
    patch: { scope: "symbols", lens: "all" },
    current: (q) => q.scope === "symbols" && q.lens === "all",
  },
  {
    label: "Market Headlines",
    patch: { scope: "market", lens: "all", tickers: [] },
    current: (q) => q.scope === "market" && q.lens === "all",
  },
  {
    label: "Everything",
    patch: { scope: "all", lens: "all" },
    current: (q) => q.scope === "all" && q.lens === "all",
  },
];

function chipClass(on: boolean): string {
  return cn(
    "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs transition-colors",
    on
      ? "border-brand/60 bg-brand/15 text-foreground"
      : "border-border-muted text-text-secondary hover:border-border hover:text-foreground",
  );
}

function Hidden({ query, omit }: { query: NewsQuery; omit: (keyof NewsQuery)[] }) {
  const fields: [string, string][] = [];
  if (!omit.includes("lens") && query.lens === "mine") fields.push(["lens", "mine"]);
  if (!omit.includes("tickers") && query.lens !== "mine" && query.tickers.length)
    fields.push(["tickers", query.tickers.join(",")]);
  if (!omit.includes("sentiment") && query.sentiment.length)
    fields.push(["sentiment", query.sentiment.join(",")]);
  if (!omit.includes("topic") && query.topic.length) fields.push(["topic", query.topic.join(",")]);
  if (!omit.includes("source") && query.source.length)
    fields.push(["source", query.source.join(",")]);
  if (!omit.includes("scope") && query.scope !== "symbols") fields.push(["scope", query.scope]);
  return (
    <>
      {fields.map(([name, value]) => (
        <input key={name} type="hidden" name={name} value={value} />
      ))}
    </>
  );
}

export function NewsFilters({
  query,
  overview,
  signedIn,
  lensTickers,
}: {
  query: NewsQuery;
  overview: NewsOverview | null;
  signedIn: boolean;
  lensTickers: string[];
}) {
  const active = activeFilterCount(query);
  const sentiments = overview?.sentiments ?? {};
  return (
    <div className="grid gap-4" data-testid="news-filters">
      <NewsSearchShortcut />
      <form
        method="GET"
        action="/news"
        aria-label="Search headlines"
        className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_auto_auto_auto] sm:items-end"
      >
        <Hidden query={query} omit={[]} />
        <label className="grid gap-1 text-xs text-text-secondary">
          Search Headlines
          <span className="relative">
            <Search
              className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-text-tertiary"
              aria-hidden
            />
            <input
              id="news-q"
              name="q"
              type="search"
              defaultValue={query.q}
              placeholder="Words in the headline, e.g. earnings guidance"
              className="h-9 w-full rounded-md border border-input bg-transparent pr-3 pl-8 text-sm text-foreground placeholder:text-text-tertiary focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/30 focus-visible:outline-none"
            />
            <kbd className="pointer-events-none absolute top-1/2 right-2 hidden -translate-y-1/2 rounded border border-border-muted px-1.5 font-mono text-3xs text-text-tertiary sm:block">
              /
            </kbd>
          </span>
        </label>
        <label className="grid gap-1 text-xs text-text-secondary">
          From
          <input
            name="from"
            type="date"
            defaultValue={query.from ?? ""}
            min={overview?.first_date ?? undefined}
            max={overview?.last_date ?? undefined}
            className="h-9 rounded-md border border-input bg-transparent px-2 text-sm text-foreground"
          />
        </label>
        <label className="grid gap-1 text-xs text-text-secondary">
          To
          <input
            name="to"
            type="date"
            defaultValue={query.to ?? ""}
            min={overview?.first_date ?? undefined}
            max={overview?.last_date ?? undefined}
            className="h-9 rounded-md border border-input bg-transparent px-2 text-sm text-foreground"
          />
        </label>
        <button
          type="submit"
          className="h-9 rounded-md border border-border bg-surface-secondary px-4 text-sm font-medium hover:bg-surface-hover"
        >
          Search
        </button>
      </form>

      <nav aria-label="News views" className="flex flex-wrap gap-1.5">
        {VIEWS.map((view) => {
          const on = view.current(query);
          return (
            <Link
              key={view.label}
              href={newsHref(query, view.patch)}
              aria-current={on ? "page" : undefined}
              className={chipClass(on)}
            >
              {view.label}
            </Link>
          );
        })}
        {signedIn ? (
          <Link
            href={newsHref(query, { lens: "mine", scope: "symbols" as NewsScope, tickers: [] })}
            aria-current={query.lens === "mine" ? "page" : undefined}
            className={chipClass(query.lens === "mine")}
            data-testid="news-lens-mine"
            title={
              lensTickers.length
                ? `Your holdings and watchlist: ${lensTickers.join(", ")}`
                : "Your holdings and watchlist"
            }
          >
            For You
          </Link>
        ) : (
          <Link
            href="/login?callbackUrl=/news?lens=mine"
            className="inline-flex items-center rounded-full px-2.5 py-1 text-xs text-text-tertiary underline-offset-4 hover:underline"
          >
            Sign in for news on your holdings
          </Link>
        )}
      </nav>

      <div className="grid gap-3">
        <div className="flex flex-wrap items-center gap-1.5" aria-label="Tone">
          <span className="mr-1 text-2xs text-text-tertiary">Tone</span>
          {NEWS_SENTIMENTS.map((s) => {
            const on = query.sentiment.includes(s);
            return (
              <Link
                key={s}
                href={newsHref(query, { sentiment: toggled(query.sentiment, s) })}
                aria-current={on ? "true" : undefined}
                className={chipClass(on)}
              >
                {titleCase(s)}
                {sentiments[s] != null ? (
                  <span className="font-mono text-3xs text-text-tertiary">{sentiments[s]}</span>
                ) : null}
              </Link>
            );
          })}
        </div>

        {overview?.topics.length ? (
          <div className="flex flex-wrap items-center gap-1.5" aria-label="Topics">
            <span className="mr-1 text-2xs text-text-tertiary">Topic</span>
            {overview.topics.slice(0, 10).map((t) => {
              const on = query.topic.includes(t.value);
              return (
                <Link
                  key={t.value}
                  href={newsHref(query, { topic: toggled(query.topic, t.value) })}
                  aria-current={on ? "true" : undefined}
                  className={chipClass(on)}
                >
                  {titleCase(t.value.replaceAll("_", " "))}
                  <span className="font-mono text-3xs text-text-tertiary">{t.count}</span>
                </Link>
              );
            })}
          </div>
        ) : null}

        {overview?.sources.length ? (
          <details className="group" open={query.source.length > 0}>
            <summary className="inline-flex cursor-pointer list-none items-center gap-1.5 text-2xs text-text-tertiary hover:text-text-secondary [&::-webkit-details-marker]:hidden">
              Sources ({overview.sources.length})
              <span className="transition-transform group-open:rotate-90" aria-hidden>
                ›
              </span>
            </summary>
            <div className="mt-2 flex flex-wrap gap-1.5" aria-label="Sources">
              {overview.sources.map((s) => {
                const on = query.source.includes(s.value);
                return (
                  <Link
                    key={s.value}
                    href={newsHref(query, { source: toggled(query.source, s.value) })}
                    aria-current={on ? "true" : undefined}
                    className={chipClass(on)}
                  >
                    {s.value}
                    <span className="font-mono text-3xs text-text-tertiary">{s.count}</span>
                  </Link>
                );
              })}
            </div>
          </details>
        ) : null}

        {active > 0 ? (
          <div className="flex flex-wrap items-center gap-1.5" data-testid="news-active-filters">
            {query.lens !== "mine"
              ? query.tickers.map((t) => (
                  <Link
                    key={t}
                    href={newsHref(query, { tickers: query.tickers.filter((x) => x !== t) })}
                    className={chipClass(true)}
                    aria-label={`Remove ${t}`}
                  >
                    <span className="ticker font-semibold">{t}</span>
                    <X className="size-3" aria-hidden />
                  </Link>
                ))
              : null}
            {query.from || query.to ? (
              <Link
                href={newsHref(query, { from: null, to: null })}
                className={chipClass(true)}
                aria-label="Remove the date range"
              >
                {query.from ? formatCloseDate(query.from) : "Start"} –{" "}
                {query.to ? formatCloseDate(query.to) : "Latest"}
                <X className="size-3" aria-hidden />
              </Link>
            ) : null}
            <Link
              href={
                query.scope === "symbols"
                  ? "/news"
                  : newsHref(
                      { ...query },
                      {
                        q: "",
                        tickers: [],
                        sentiment: [],
                        topic: [],
                        source: [],
                        from: null,
                        to: null,
                        lens: "all",
                      },
                    )
              }
              className="px-1 text-xs text-text-tertiary underline-offset-4 hover:text-foreground hover:underline"
            >
              Clear All
            </Link>
          </div>
        ) : null}
      </div>
    </div>
  );
}
