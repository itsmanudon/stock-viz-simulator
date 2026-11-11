import type { Metadata } from "next";

import {
  EarningsCalendar,
  type EarningsScope,
  type EarningsView,
  viewRange,
} from "@/components/earnings-calendar";
import { PageFrame } from "@/components/page-frame";
import { MetaChip, PageHeader } from "@/components/page-header";
import { getEarningsCalendar } from "@/lib/api/earnings";

export const metadata: Metadata = { title: "Earnings" };

function parseDate(value: string | undefined): Date {
  if (value && /^\d{4}-\d{2}-\d{2}$/.test(value)) {
    const date = new Date(`${value}T12:00:00Z`);
    if (!Number.isNaN(date.valueOf())) return date;
  }
  const today = new Date();
  return new Date(Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate()));
}

export default async function EarningsPage({
  searchParams,
}: {
  searchParams: Promise<{ date?: string; view?: string; scope?: string }>;
}) {
  const params = await searchParams;
  const anchor = parseDate(params.date);
  const view: EarningsView =
    params.view === "day" || params.view === "week" ? params.view : "month";
  const scope: EarningsScope =
    params.scope === "holdings" || params.scope === "watchlist" ? params.scope : "all";
  const range = viewRange(anchor, view);
  const events = await getEarningsCalendar({ ...range, scope }).catch(() => []);

  return (
    <PageFrame width="workstation" className="py-5 sm:py-7">
      <PageHeader
        eyebrow="Research · calendar"
        title="Earnings"
        description="Scheduled and reported earnings from the stored provider feed. A result shows only when both reported and estimated EPS exist."
        meta={
          <span className="flex flex-wrap items-center gap-2">
            <span>
              {events.length} report{events.length === 1 ? "" : "s"} in view
            </span>
            <MetaChip>Dates in UTC</MetaChip>
          </span>
        }
      />

      <section
        className="mt-6 rounded-xl border border-border-muted bg-card p-3 sm:p-4"
        aria-label="Earnings calendar"
      >
        <EarningsCalendar events={events} view={view} scope={scope} anchor={anchor} />
      </section>
      <p className="mt-4 text-2xs leading-relaxed text-text-tertiary">
        Provider timestamps may be broad (before market, after market, or unknown). StockViz uses
        end-of-day prices and does not treat this calendar as a live alert.
      </p>
    </PageFrame>
  );
}
