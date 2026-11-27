/**
 * /checklist — the Checklist (A2.4, M4.4), which replaced the 7-vote Signals.
 *
 * Six published conditions per symbol (Trend, Momentum / relative strength,
 * Volume / delivery, Market regime, Quality, Risk / reward), each met, not
 * met or unknown on the symbol's latest stored session, with its formula,
 * its evidence grade and the sample behind the grade. URL state: `min`
 * (at least N met), `dimension` (must be met), `sort` (met | ticker), `q`.
 * Neutral wording only: "N of 6 met" is a count, not a call to act.
 */

import type { Metadata } from "next";
import Link from "next/link";

import {
  ChecklistMatrixHeader,
  ChecklistSymbol,
  DimensionGuide,
} from "@/components/checklist/checklist-view";
import { PageFrame } from "@/components/page-frame";
import {
  ResearchEmptyState,
  ResearchPageHeader,
  ResearchSubnav,
} from "@/components/research-page-header";
import { UniverseNote } from "@/components/universe-note";
import { getChecklist } from "@/lib/api";
import {
  CHECKLIST_TOTAL,
  type ChecklistSearchParams,
  type ChecklistSort,
  buildChecklistHref,
  filterChecklistRows,
  parseChecklistSort,
  parseDimension,
  parseMinMet,
} from "@/lib/checklist-view";

export const metadata: Metadata = { title: "Checklist" };

export default async function ChecklistPage({
  searchParams,
}: {
  searchParams: Promise<ChecklistSearchParams>;
}) {
  const params = await searchParams;
  const checklist = await getChecklist({ limit: 500 });
  const keys = checklist.dimensions.map((d) => d.key);
  const min = parseMinMet(params.min);
  const dimension = parseDimension(params.dimension, keys);
  const sort = parseChecklistSort(params.sort);
  const query = params.q?.trim() || undefined;

  const filtered = checklist.rows.filter(
    (row) =>
      row.met >= min &&
      (!dimension ||
        row.results.some((result) => result.key === dimension && result.status === "met")),
  );
  const rows = filterChecklistRows(filtered, { query, sort });
  const sessions = Array.from(new Set(checklist.rows.map((row) => row.session_date))).sort();
  const latest = sessions.at(-1);
  const exact = query ? rows.find((row) => row.ticker === query.toUpperCase()) : undefined;

  const hrefFor = (
    overrides: Partial<{ min: number; dimension: string; sort: ChecklistSort; q: string }>,
  ) =>
    buildChecklistHref({
      min: overrides.min ?? min,
      dimension: overrides.dimension === "" ? undefined : (overrides.dimension ?? dimension),
      sort: overrides.sort ?? sort,
      q: overrides.q === "" ? undefined : (overrides.q ?? query),
    });

  return (
    <PageFrame width="workstation" className="py-5 sm:py-7">
      <ResearchPageHeader
        title="Checklist"
        description="Six published conditions per symbol, each met, not met or unknown on its latest stored session, with the formula and how it graded in the past. A count of conditions, not a recommendation and not financial advice."
        meta={latest ? `Latest session ${latest}` : undefined}
      />
      <ResearchSubnav current="/checklist" />

      <form method="GET" action="/checklist" className="mt-5 flex flex-wrap items-end gap-3">
        {min > 0 ? <input type="hidden" name="min" value={min} /> : null}
        {sort !== "met" ? <input type="hidden" name="sort" value={sort} /> : null}
        <label className="space-y-1 text-xs">
          <span className="block font-medium text-text-secondary">Dimension met</span>
          <select
            name="dimension"
            defaultValue={dimension ?? ""}
            className="h-9 min-w-40 rounded-md border border-input bg-transparent px-2 text-sm"
          >
            <option value="">Any</option>
            {checklist.dimensions.map((d) => (
              <option key={d.key} value={d.key}>
                {d.name}
              </option>
            ))}
          </select>
        </label>
        <label className="space-y-1 text-xs">
          <span className="block font-medium text-text-secondary">Ticker or name</span>
          <input
            name="q"
            defaultValue={query ?? ""}
            placeholder="AAPL"
            className="h-9 w-36 rounded-md border border-input bg-transparent px-2 font-mono text-sm"
          />
        </label>
        <button
          type="submit"
          className="h-9 rounded-md border border-border-muted px-3 text-sm hover:bg-surface-hover"
        >
          Apply
        </button>
      </form>

      <div className="mt-4 flex flex-wrap items-center justify-between gap-3 text-xs">
        <nav aria-label="Minimum dimensions met" className="flex flex-wrap gap-1">
          {Array.from({ length: CHECKLIST_TOTAL + 1 }, (_, n) => n).map((threshold) => (
            <Link
              key={threshold}
              href={hrefFor({ min: threshold })}
              aria-current={min === threshold ? "true" : undefined}
              className={`rounded-sm border px-2.5 py-1 transition-colors hover:bg-surface-hover ${
                min === threshold
                  ? "border-brand text-foreground"
                  : "border-border-muted text-text-tertiary"
              }`}
            >
              {threshold === 0 ? "All" : `At least ${threshold} of ${CHECKLIST_TOTAL}`}
            </Link>
          ))}
        </nav>
        <nav aria-label="Sort" className="flex items-center gap-1">
          <span className="text-text-tertiary">Sort:</span>
          {(
            [
              ["met", "Most met"],
              ["ticker", "Ticker"],
            ] as const
          ).map(([key, label]) => (
            <Link
              key={key}
              href={hrefFor({ sort: key })}
              aria-current={sort === key ? "true" : undefined}
              className={`rounded-sm border px-2.5 py-1 hover:bg-surface-hover ${
                sort === key
                  ? "border-brand text-foreground"
                  : "border-border-muted text-text-tertiary"
              }`}
            >
              {label}
            </Link>
          ))}
        </nav>
      </div>

      <div className="mt-6">
        <DimensionGuide dimensions={checklist.dimensions} />
      </div>

      <section aria-labelledby="checklist-symbols" className="mt-6 space-y-2">
        <h2 id="checklist-symbols" className="text-sm font-semibold tracking-tight">
          Symbols <span className="font-normal text-text-tertiary">({rows.length})</span>
        </h2>
        {rows.length === 0 ? (
          <ResearchEmptyState title="No symbols match these filters">
            <p>
              Lower the minimum or clear the dimension, or score the universe with{" "}
              <code className="rounded-sm bg-muted px-1.5 py-0.5 text-xs">
                stockviz.cli checklist
              </code>
              .
            </p>
          </ResearchEmptyState>
        ) : (
          <ChecklistMatrixHeader dimensions={checklist.dimensions} />
        )}
        {rows.length === 0
          ? null
          : rows.map((row) => (
              <ChecklistSymbol
                key={row.ticker}
                row={row}
                dimensions={checklist.dimensions}
                open={row.ticker === exact?.ticker}
              />
            ))}
      </section>

      <div className="mt-6 space-y-2">
        <UniverseNote universe={checklist.universe} />
        <p className="text-xs leading-5 text-text-tertiary" data-testid="checklist-disclaimer">
          {checklist.disclaimer}
        </p>
      </div>
    </PageFrame>
  );
}
