/**
 * /news — the news archive (news redesign, 26 Nov 2026).
 *
 * Reads `/v1/news/feed` (one page, keyset paging through the whole archive,
 * every filter, each headline's price reaction) and `/v1/news/overview`
 * (timeline, filter counts, coverage heatmap) in parallel. URL state only
 * (`lib/news-view.ts`): `q`, `tickers`, `sentiment`, `topic`, `source`,
 * `scope` (symbols | market | all), `from`, `to`, `cursor`, `lens=mine`
 * (signed in: the holdings and watchlist, like the dashboard's news card).
 *
 * Headline, source, dates and links only: the Aegis read contract stores no
 * article text, so there are no summaries. Each part degrades on its own: a
 * failed overview drops the timeline, heatmap and counts; a failed feed says
 * so and keeps the filters.
 */

import type { Metadata } from "next";
import Link from "next/link";

import { auth } from "@/auth";
import { CoverageHeatmap } from "@/components/news/coverage-heatmap";
import { NewsFeed } from "@/components/news/news-feed";
import { NewsFilters } from "@/components/news/news-filters";
import { NewsTimeline } from "@/components/news/news-timeline";
import { PageEmptyState } from "@/components/page-header";
import { ResearchPageHeader, ResearchSubnav } from "@/components/research-page-header";
import { VisitorLimitNotice } from "@/components/visitor-limit-notice";
import { type NewsFeed as NewsFeedData, getNewsFeed, getNewsOverview } from "@/lib/api/news";
import type { NewsOverview } from "@/lib/api/news";
import { getPortfolio } from "@/lib/api/trading";
import { listWatchlist } from "@/lib/api/watchlist";
import { dashboardNewsTickers } from "@/lib/dashboard-news";
import { groupByDay, groupStories, newsApiParams, newsHref, parseNewsQuery } from "@/lib/news-view";
import { checkVisitorLimit } from "@/lib/visitor-limit";

export const metadata: Metadata = { title: "News" };

const PAGE_SIZE = 40;

async function optional<T>(load: Promise<T>): Promise<T | null> {
  try {
    return await load;
  } catch {
    return null;
  }
}

async function lensTickers(): Promise<string[]> {
  const [portfolio, watchlist] = await Promise.all([
    optional(getPortfolio()),
    optional(listWatchlist()),
  ]);
  return dashboardNewsTickers(portfolio?.positions ?? [], watchlist);
}

export default async function NewsPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const visitorLimit = await checkVisitorLimit("news");
  if (!visitorLimit.allowed) {
    return <VisitorLimitNotice retryAfterSeconds={visitorLimit.retryAfterSeconds} />;
  }
  const query = parseNewsQuery(await searchParams);
  const session = await auth();
  const signedIn = Boolean(session?.user);
  const mine = signedIn && query.lens === "mine" ? await lensTickers() : [];
  const tickers = query.lens === "mine" ? mine : query.tickers;
  const noLensTickers = signedIn && query.lens === "mine" && mine.length === 0;

  const params = newsApiParams(query, tickers, PAGE_SIZE);
  const [feed, overview] = noLensTickers
    ? [null, null]
    : await Promise.all([
        optional<NewsFeedData>(getNewsFeed(params)),
        optional<NewsOverview>(getNewsOverview(params)),
      ]);
  const days = feed ? groupByDay(groupStories(feed.items)) : [];
  const shown = feed?.items.length ?? 0;

  return (
    <div className="container mx-auto px-4 py-6 sm:px-6 lg:py-7">
      <ResearchPageHeader
        path="/news"
        title="News"
        description="Every headline Aegis News has linked, searchable back to the first one, with what each stock did on the session after. Headlines, sources and dates only; open the original to read the article."
      />
      <ResearchSubnav current="/news" />

      <div className="mt-5 grid gap-6">
        <NewsFilters query={query} overview={overview} signedIn={signedIn} lensTickers={mine} />

        {overview && overview.days.length > 1 ? (
          <NewsTimeline days={overview.days} query={query} />
        ) : null}

        <div className="grid gap-8 xl:grid-cols-[minmax(0,1fr)_minmax(0,26rem)] xl:items-start">
          <section aria-labelledby="headlines-heading" className="min-w-0">
            <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
              <h2 id="headlines-heading" className="text-sm font-semibold tracking-tight">
                Headlines
              </h2>
              {feed ? (
                <p className="font-mono text-xs text-text-tertiary" data-testid="news-count">
                  {feed.total.toLocaleString("en-US")} match
                  {feed.total === 1 ? "" : "es"}
                  {query.cursor ? ` · older page, ${shown} shown` : ""}
                </p>
              ) : null}
            </div>

            {noLensTickers ? (
              <PageEmptyState
                title="Nothing to follow yet"
                action={
                  <Link href="/watchlist" className="text-sm underline underline-offset-4">
                    Open your watchlist
                  </Link>
                }
              >
                For You reads the symbols you hold and watch. Add a symbol to your watchlist or
                place a paper trade, and its headlines show here.
              </PageEmptyState>
            ) : feed == null ? (
              <PageEmptyState title="News could not be loaded just now">
                The news service did not answer. Try again in a moment; your filters are kept in the
                address.
              </PageEmptyState>
            ) : shown === 0 ? (
              <PageEmptyState
                title="No headlines match"
                action={
                  <Link href="/news" className="text-sm underline underline-offset-4">
                    Clear all filters
                  </Link>
                }
              >
                Try fewer words, another tone or a wider date range. News is copied from Aegis News
                once a night.
              </PageEmptyState>
            ) : (
              <>
                <NewsFeed days={days} isFirstPage={!query.cursor} />
                <nav
                  aria-label="News pages"
                  className="mt-6 flex items-center justify-between gap-3 text-sm"
                >
                  {query.cursor ? (
                    <Link
                      href={newsHref(query)}
                      className="rounded-md border border-border-muted px-3 py-1.5 hover:bg-surface-hover"
                    >
                      ← Newest
                    </Link>
                  ) : (
                    <span />
                  )}
                  {feed.next_cursor ? (
                    <Link
                      href={newsHref(query, { cursor: feed.next_cursor })}
                      className="rounded-md border border-border-muted px-3 py-1.5 hover:bg-surface-hover"
                      data-testid="news-older"
                    >
                      Older headlines →
                    </Link>
                  ) : (
                    <span className="text-xs text-text-tertiary">The start of the archive</span>
                  )}
                </nav>
              </>
            )}
            <p className="mt-6 text-xs leading-5 text-text-tertiary">
              {feed?.note ??
                "Headlines, sources, dates and links only: Aegis News stores no article text."}{" "}
              Tone is Aegis&rsquo;s label for the headline, not a recommendation.
            </p>
          </section>

          {overview ? (
            <aside className="min-w-0 xl:sticky xl:top-20">
              <CoverageHeatmap rows={overview.heatmap} days={overview.heatmap_days} query={query} />
            </aside>
          ) : null}
        </div>
      </div>
    </div>
  );
}
