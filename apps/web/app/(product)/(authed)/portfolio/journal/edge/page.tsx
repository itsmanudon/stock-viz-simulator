/**
 * /portfolio/journal/edge — A5.6 (M10.3 stats): "Is my edge real?" over the
 * closed journal entries. A sub-view of the Portfolio Journal tab (mapped to
 * the Portfolio item through its `/portfolio/journal` prefix): the overall
 * strip, the table by setup, tag and source with n and the seeded 90%
 * bootstrap interval (or counts only under 30), and one drift card per setup
 * against its newest saved backtest. URL state: `book` (an id, else every
 * book), `source`, `tag`, `setup`, `from`, `to`. Every figure comes from
 * `/v1/journal/stats`, computed on read.
 */

import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { BehaviourView } from "@/components/journal/behaviour-view";
import {
  EdgeDriftCard,
  EdgeGroupsTable,
  EdgeHonesty,
  EdgeOverview,
} from "@/components/journal/edge-view";
import { MetaChip, PageHeader } from "@/components/page-header";
import { type Behaviour, getJournalBehaviour, getJournalStats } from "@/lib/api/journal-edge";
import { AuthedApiError } from "@/lib/api/server";
import {
  type EdgeFilters,
  type EdgeSource,
  type EdgeStats,
  SOURCE_OPTIONS,
  edgeHref,
} from "@/lib/journal-edge";

export const metadata: Metadata = { title: "Is my edge real?" };

const SOURCES: readonly EdgeSource[] = ["paper", "imported", "replay", "all"];
const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

type Search = {
  book?: string;
  source?: string;
  tag?: string;
  setup?: string;
  from?: string;
  to?: string;
};

function parseFilters(raw: Search): EdgeFilters {
  const setup = Number(raw.setup);
  return {
    source: SOURCES.includes(raw.source as EdgeSource) ? (raw.source as EdgeSource) : undefined,
    tag: raw.tag?.trim() ? raw.tag.trim().slice(0, 32) : undefined,
    setupVersionId: Number.isInteger(setup) && setup > 0 ? setup : undefined,
    from: raw.from && ISO_DATE.test(raw.from) ? raw.from : undefined,
    to: raw.to && ISO_DATE.test(raw.to) ? raw.to : undefined,
  };
}

function parseBook(raw: string | undefined): number | "all" | null {
  if (raw === "all") return "all";
  const id = Number(raw);
  return Number.isInteger(id) && id > 0 ? id : null;
}

export default async function EdgePage({ searchParams }: { searchParams: Promise<Search> }) {
  const raw = await searchParams;
  const book = parseBook(raw.book);
  const filters = parseFilters(raw);
  let stats: EdgeStats | null = null;
  try {
    stats = await getJournalStats(book, filters);
  } catch (error) {
    if (error instanceof AuthedApiError && error.status === 404) notFound();
    stats = null;
  }
  // A7.6: behaviour diagnostics over the same book, source and dates.
  const behaviour: Behaviour | null = await getJournalBehaviour(book, filters).catch(() => null);
  const back = `/portfolio?tab=journal${book ? `&book=${book}` : ""}`;
  const activeSource = filters.source ?? "live";

  return (
    <div className="mx-auto w-full max-w-6xl space-y-8 px-4 py-6 sm:px-6 lg:py-7">
      <div>
        <Link
          href={back}
          className="text-sm text-text-secondary underline-offset-2 hover:underline"
        >
          ← Journal
        </Link>
      </div>
      <PageHeader
        eyebrow="Portfolio · Journal"
        title="Is My Edge Real?"
        description="What your closed trades say so far, with how sure the sample lets you be. Figures are net of fees and computed from your journal each time you open this page."
        meta={
          <span className="flex flex-wrap items-center gap-2">
            <MetaChip>{typeof book === "number" ? "One book" : "All books and replay"}</MetaChip>
            {stats ? <MetaChip>Seed {stats.seed}</MetaChip> : null}
            {stats?.imported_fees_estimated ? (
              <MetaChip tone="warning">Imported charges estimated</MetaChip>
            ) : null}
          </span>
        }
      />

      <nav aria-label="Trades included" className="flex flex-wrap items-center gap-1.5">
        {SOURCE_OPTIONS.map((o) => {
          const active = o.value === activeSource;
          return (
            <Link
              key={o.value}
              href={edgeHref(book, {
                ...filters,
                source: o.value === "live" ? undefined : o.value,
              })}
              aria-current={active ? "page" : undefined}
              data-testid="edge-source"
              className={`rounded-full border px-3 py-1 text-xs tracking-[0.02em] ${
                active
                  ? "border-brand bg-brand/10 text-foreground"
                  : "border-border-muted text-text-secondary hover:text-foreground"
              }`}
            >
              {o.label}
            </Link>
          );
        })}
        {filters.tag ? (
          <Link
            href={edgeHref(book, { ...filters, tag: undefined })}
            className="rounded-full border border-border-muted px-3 py-1 text-xs text-text-secondary hover:text-foreground"
            aria-label={`Remove the tag filter ${filters.tag}`}
          >
            Tag: {filters.tag} ×
          </Link>
        ) : null}
        {filters.setupVersionId ? (
          <Link
            href={edgeHref(book, { ...filters, setupVersionId: undefined })}
            className="rounded-full border border-border-muted px-3 py-1 text-xs text-text-secondary hover:text-foreground"
            aria-label="Remove the setup filter"
          >
            One setup ×
          </Link>
        ) : null}
      </nav>

      {stats === null ? (
        <p className="text-sm text-text-secondary">These statistics are unavailable right now.</p>
      ) : (
        <>
          <EdgeHonesty notes={stats.honesty} />
          <EdgeOverview stats={stats} />
          <p className="-mt-5 text-xs text-text-tertiary" data-testid="edge-method">
            {stats.method} Paper, imported and replay are never pooled unless you pick All Sources.
            {stats.open_excluded
              ? ` ${stats.open_excluded} open ${stats.open_excluded === 1 ? "entry is" : "entries are"} left out until closed.`
              : ""}
          </p>

          <Section title="By Setup" id="edge-setups">
            <EdgeGroupsTable groups={stats.by_setup} caption="Edge by setup version" />
          </Section>
          <Section title="Live vs Backtest" id="edge-drift">
            {stats.drift.length === 0 ? (
              <p className="text-sm text-text-secondary">
                No trade here was planned with a setup, so there is nothing to compare.
              </p>
            ) : (
              <div className="grid gap-4 lg:grid-cols-2">
                {stats.drift.map((d) => (
                  <EdgeDriftCard key={d.setup_version_id} drift={d} />
                ))}
              </div>
            )}
          </Section>
          <Section title="By Setup Tag" id="edge-setup-tags">
            <EdgeGroupsTable groups={stats.by_setup_tag} caption="Edge by setup tag" />
          </Section>
          <Section title="By Mistake Tag" id="edge-mistake-tags">
            <EdgeGroupsTable groups={stats.by_mistake_tag} caption="Edge by mistake tag" />
          </Section>
          <Section title="By Source" id="edge-sources">
            <EdgeGroupsTable groups={stats.by_source} caption="Edge by source" />
          </Section>
          {behaviour ? (
            <Section title="Behaviour" id="edge-behaviour">
              <BehaviourView behaviour={behaviour} />
            </Section>
          ) : null}
        </>
      )}
    </div>
  );
}

function Section({
  title,
  id,
  children,
}: { title: string; id: string; children: React.ReactNode }) {
  return (
    <section aria-labelledby={id} className="space-y-3">
      <h2 id={id} className="text-base font-semibold tracking-tight">
        {title}
      </h2>
      {children}
    </section>
  );
}
