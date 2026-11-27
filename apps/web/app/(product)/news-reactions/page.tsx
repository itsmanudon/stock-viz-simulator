/**
 * /news-reactions — news event studies (Phase 7.4).
 *
 * How did stocks move, against their market index, around news of a kind?
 * Pick symbols, a sentiment label or an Aegis event type, and the window;
 * the URL holds the query, so a study can be shared. Public, rate-limited
 * per visitor like the screener.
 */

import type { Metadata } from "next";

import { EventStudyView } from "@/components/event-study-view";
import { PageFrame } from "@/components/page-frame";
import { ResearchPageHeader, ResearchSubnav } from "@/components/research-page-header";
import { VisitorLimitNotice } from "@/components/visitor-limit-notice";
import { ApiError } from "@/lib/api";
import { getMarketsSummary } from "@/lib/api";
import { type EventStudy, getEventStudy } from "@/lib/api/research";
import { checkVisitorLimit } from "@/lib/visitor-limit";

export const metadata: Metadata = { title: "News reactions" };

const SENTIMENTS = ["negative", "positive", "mixed", "neutral"] as const;

function tickersOf(raw: string | string[] | undefined): string[] {
  const list = Array.isArray(raw) ? raw : raw ? [raw] : [];
  return [
    ...new Set(
      list
        .flatMap((t) => t.split(","))
        .map((t) => t.trim().toUpperCase())
        .filter(Boolean),
    ),
  ].slice(0, 20);
}

function bounded(raw: string | undefined, fallback: number, max: number): number {
  const n = Number(raw);
  return Number.isInteger(n) && n >= 1 && n <= max ? n : fallback;
}

export default async function NewsReactionsPage({
  searchParams,
}: {
  searchParams: Promise<{
    tickers?: string | string[];
    sentiment?: string;
    event_type?: string;
    pre?: string;
    post?: string;
  }>;
}) {
  const visitorLimit = await checkVisitorLimit("reactions");
  if (!visitorLimit.allowed) {
    return <VisitorLimitNotice retryAfterSeconds={visitorLimit.retryAfterSeconds} />;
  }
  const params = await searchParams;
  const tickers = tickersOf(params.tickers);
  const sentiment = SENTIMENTS.find((s) => s === params.sentiment) ?? "";
  const eventType = (params.event_type ?? "").slice(0, 128);
  const pre = bounded(params.pre, 5, 20);
  const post = bounded(params.post, 20, 60);

  const summary = await getMarketsSummary().catch(() => ({ rows: [], sectors: [] }));
  let study: EventStudy | null = null;
  let error: string | null = null;
  if (tickers.length) {
    try {
      study = await getEventStudy({
        tickers,
        sentiment: sentiment || undefined,
        eventType: eventType || undefined,
        pre,
        post,
      });
    } catch (err) {
      error = err instanceof ApiError ? err.message : "The study could not be run.";
    }
  }

  return (
    <PageFrame width="workstation" className="py-5 sm:py-7">
      <ResearchPageHeader
        title="News reactions"
        description="How did prices move against their market index around news of a kind? Market-adjusted returns from the first session that closed after each Aegis item became available."
      />
      <ResearchSubnav current="/news-reactions" />

      <form
        method="GET"
        className="mt-5 grid gap-3 rounded-md border border-border-muted bg-card p-4 sm:grid-cols-[2fr_1fr_1fr_auto_auto_auto] sm:items-end"
      >
        <label className="grid gap-1.5 text-xs">
          Symbols (comma-separated)
          <input
            name="tickers"
            defaultValue={tickers.join(",")}
            list="reaction-symbols"
            placeholder="AAPL,MSFT or RELIANCE.NS"
            className="h-9 rounded-sm border border-input bg-transparent px-2 font-mono text-sm uppercase placeholder:font-sans placeholder:normal-case"
          />
          <datalist id="reaction-symbols">
            {summary.rows.map((r) => (
              <option key={r.ticker} value={r.ticker} label={r.name} />
            ))}
          </datalist>
        </label>
        <label className="grid gap-1.5 text-xs">
          Sentiment
          <select
            name="sentiment"
            defaultValue={sentiment}
            className="h-9 rounded-sm border border-input bg-transparent px-2 text-sm"
          >
            <option value="">Any</option>
            {SENTIMENTS.map((s) => (
              <option key={s} value={s}>
                {s[0].toUpperCase() + s.slice(1)}
              </option>
            ))}
          </select>
        </label>
        <label className="grid gap-1.5 text-xs">
          Event type
          <input
            name="event_type"
            defaultValue={eventType}
            maxLength={128}
            className="h-9 rounded-sm border border-input bg-transparent px-2 text-sm"
          />
        </label>
        <label className="grid gap-1.5 text-xs">
          Days before
          <input
            name="pre"
            type="number"
            min={1}
            max={20}
            defaultValue={pre}
            className="h-9 w-20 rounded-sm border border-input bg-transparent px-2 font-mono text-sm"
          />
        </label>
        <label className="grid gap-1.5 text-xs">
          Days after
          <input
            name="post"
            type="number"
            min={1}
            max={60}
            defaultValue={post}
            className="h-9 w-20 rounded-sm border border-input bg-transparent px-2 font-mono text-sm"
          />
        </label>
        <button
          type="submit"
          className="h-9 rounded-full bg-primary px-5 text-sm font-medium text-primary-foreground"
        >
          Run study
        </button>
      </form>

      <section
        aria-label="Study results"
        className="mt-6 rounded-md border border-border-muted bg-card p-4"
      >
        {error ? (
          <p className="text-sm text-negative" role="alert">
            {error}
          </p>
        ) : study ? (
          <EventStudyView study={study} />
        ) : (
          <p className="text-sm text-text-secondary">
            Pick one or more symbols to study. Indices are the benchmarks: S&amp;P 500 for US
            listings, NIFTY 50 for Indian ones.
          </p>
        )}
      </section>
    </PageFrame>
  );
}
