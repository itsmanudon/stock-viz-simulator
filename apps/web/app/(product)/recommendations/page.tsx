/**
 * /recommendations — Signals workspace.
 *
 * Rule-based, explainable votes over the tracked universe. The route stays
 * `/recommendations`; the surface is titled Signals so it is not mistaken for
 * an AI buy list.
 */

import Link from "next/link";

import { PageFrame } from "@/components/page-frame";
import {
  ResearchEmptyState,
  ResearchPageHeader,
  ResearchSubnav,
} from "@/components/research-page-header";
import { SignalsTable } from "@/components/signals-table";
import { getRecommendations } from "@/lib/api";
import {
  type SignalFilter,
  type SignalSearchParams,
  type SignalSortKey,
  buildSignalsHref,
  filterSignals,
  parseMinScore,
  parseSignalFilter,
  parseSignalSort,
  parseSignalSortDir,
  recommendationToSignal,
  sortSignals,
} from "@/lib/signals-workspace";

export default async function RecommendationsPage({
  searchParams,
}: {
  searchParams: Promise<SignalSearchParams>;
}) {
  const params = await searchParams;
  const minScore = parseMinScore(params.min);
  const signal = parseSignalFilter(params.signal);
  const sort = parseSignalSort(params.sort);
  const dir = parseSignalSortDir(params.dir, sort);
  const sector = params.sector?.trim() || undefined;
  const query = params.q?.trim() || undefined;

  const recs = await getRecommendations({ minScore, limit: 100 });
  const allRows = recs.map(recommendationToSignal);
  const sectors = Array.from(
    new Set(allRows.map((row) => row.sector).filter((value): value is string => Boolean(value))),
  ).sort();
  const rows = sortSignals(filterSignals(allRows, { signal, sector, query }), sort, dir);

  const lastComputed = rows.length
    ? rows.reduce(
        (latest, row) => (row.computedAt > latest ? row.computedAt : latest),
        rows[0].computedAt,
      )
    : null;

  const hrefFor = (
    overrides: Partial<{
      min: number;
      signal: SignalFilter;
      sector: string;
      q: string;
      sort: SignalSortKey;
      dir: "asc" | "desc";
    }>,
  ) =>
    buildSignalsHref({
      min: overrides.min ?? minScore,
      signal: overrides.signal ?? signal,
      sector: overrides.sector === "" ? undefined : (overrides.sector ?? sector),
      q: overrides.q === "" ? undefined : (overrides.q ?? query),
      sort: overrides.sort ?? sort,
      dir: overrides.dir ?? dir,
    });

  function sortHref(key: SignalSortKey): string {
    const nextDir =
      sort === key && dir === "desc"
        ? "asc"
        : sort === key && dir === "asc"
          ? "desc"
          : key === "ticker"
            ? "asc"
            : "desc";
    return hrefFor({ sort: key, dir: nextDir });
  }

  return (
    <PageFrame width="workstation" className="py-6 sm:py-8">
      <ResearchPageHeader
        title="Signals"
        description="Explainable technical and sentiment evidence across the tracked universe. This is a seven-vote rule set, not an AI recommendation and not financial advice."
        meta={
          lastComputed
            ? `Last computed ${new Date(lastComputed).toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" })}`
            : undefined
        }
      />
      <ResearchSubnav current="/recommendations" />

      <form method="GET" action="/recommendations" className="mt-6 flex flex-wrap items-end gap-3">
        {minScore > 0 ? <input type="hidden" name="min" value={minScore} /> : null}
        {sort !== "score" ? <input type="hidden" name="sort" value={sort} /> : null}
        {dir !== "desc" ? <input type="hidden" name="dir" value={dir} /> : null}

        <label className="space-y-1 text-xs">
          <span className="block font-medium text-text-secondary">Signal</span>
          <select
            name="signal"
            defaultValue={signal}
            className="h-9 rounded-sm border border-input bg-transparent px-2 text-sm"
          >
            <option value="all">All</option>
            <option value="bullish">Bullish</option>
            <option value="neutral">Neutral</option>
          </select>
        </label>

        <label className="space-y-1 text-xs">
          <span className="block font-medium text-text-secondary">Sector</span>
          <select
            name="sector"
            defaultValue={sector ?? ""}
            className="h-9 min-w-40 rounded-sm border border-input bg-transparent px-2 text-sm"
          >
            <option value="">All sectors</option>
            {sectors.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>
        </label>

        <label className="space-y-1 text-xs">
          <span className="block font-medium text-text-secondary">Ticker</span>
          <input
            name="q"
            defaultValue={query ?? ""}
            placeholder="AAPL"
            className="h-9 w-32 rounded-sm border border-input bg-transparent px-2 font-mono text-sm"
          />
        </label>

        <button
          type="submit"
          className="h-9 rounded-sm border border-border-muted px-3 text-sm hover:bg-surface-hover"
        >
          Apply
        </button>
      </form>

      <nav aria-label="Minimum supporting votes" className="mt-4 flex flex-wrap gap-1 text-xs">
        {[0, 3, 4, 5, 6].map((threshold) => (
          <Link
            key={threshold}
            href={hrefFor({ min: threshold })}
            className={`rounded-sm border px-2.5 py-1 transition-colors hover:bg-surface-hover ${
              minScore === threshold
                ? "border-brand text-foreground"
                : "border-border-muted text-text-tertiary"
            }`}
          >
            {threshold === 0 ? "All scores" : `≥ ${threshold}`}
          </Link>
        ))}
      </nav>

      <div className="mt-6">
        {rows.length === 0 ? (
          <ResearchEmptyState title="No signals match these filters">
            <p>
              Relax the score threshold or signal class, or recompute with{" "}
              <code className="rounded-sm bg-muted px-1.5 py-0.5 text-xs">stockviz recommend</code>.
            </p>
          </ResearchEmptyState>
        ) : (
          <SignalsTable rows={rows} sort={sort} dir={dir} sortHref={sortHref} />
        )}
      </div>
    </PageFrame>
  );
}
