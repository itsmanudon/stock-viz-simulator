import { CalendarDays } from "lucide-react";

import {
  EarningsCalendar,
  type EarningsScope,
  type EarningsView,
} from "@/components/earnings-calendar";
import { PageFrame } from "@/components/page-frame";
import { getEarningsCalendar } from "@/lib/api/earnings";

function parseDate(value: string | undefined): Date {
  if (value && /^\d{4}-\d{2}-\d{2}$/.test(value)) {
    const date = new Date(`${value}T12:00:00Z`);
    if (!Number.isNaN(date.valueOf())) return date;
  }
  const today = new Date();
  return new Date(Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate()));
}

function rangeFor(anchor: Date, view: EarningsView): { from: string; to: string } {
  if (view === "month") {
    return {
      from: new Date(Date.UTC(anchor.getUTCFullYear(), anchor.getUTCMonth(), 1))
        .toISOString()
        .slice(0, 10),
      to: new Date(Date.UTC(anchor.getUTCFullYear(), anchor.getUTCMonth() + 1, 0))
        .toISOString()
        .slice(0, 10),
    };
  }
  const start = new Date(anchor);
  if (view === "week") start.setUTCDate(start.getUTCDate() - start.getUTCDay());
  const end = new Date(start);
  if (view === "week") end.setUTCDate(end.getUTCDate() + 6);
  return { from: start.toISOString().slice(0, 10), to: end.toISOString().slice(0, 10) };
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
  const range = rangeFor(anchor, view);
  const events = await getEarningsCalendar({ ...range, scope }).catch(() => []);

  return (
    <PageFrame width="workstation" className="py-5 sm:py-7">
      <header className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-2xs font-semibold tracking-[0.14em] text-brand uppercase">
            Research / calendar
          </p>
          <h1 className="mt-1.5 flex items-center gap-2 text-3xl font-semibold tracking-tight">
            <CalendarDays className="size-7 text-brand" aria-hidden /> Earnings
          </h1>
          <p className="mt-1.5 max-w-2xl text-sm leading-6 text-text-secondary">
            Scheduled and reported earnings from the stored provider feed. Results are shown only
            when both reported and estimated EPS are available.
          </p>
        </div>
        <p className="text-xs text-text-tertiary">
          {events.length} event{events.length === 1 ? "" : "s"} in view
        </p>
      </header>

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
