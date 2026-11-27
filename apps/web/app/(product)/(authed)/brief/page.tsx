/**
 * /brief — A9.12 (M11.6): the morning brief for the symbols you hold or watch.
 * Every move is dated by its two closes (end of day, never a live quote).
 */

import type { Metadata } from "next";
import Link from "next/link";

import { PageEmptyState, PageHeader } from "@/components/page-header";
import { formatUtcDateTime } from "@/lib/api-time";
import { type MorningBrief, getBrief } from "@/lib/api/brief";
import { moveText } from "@/lib/brief";
import { formatCloseDate } from "@/lib/stock-workspace";

export const metadata: Metadata = { title: "Morning Brief" };

export default async function BriefPage() {
  let brief: MorningBrief | null = null;
  try {
    brief = await getBrief();
  } catch {
    brief = null;
  }
  return (
    <div className="w-full space-y-6 px-4 py-6 sm:px-6 lg:py-7 xl:px-8">
      <PageHeader
        eyebrow="Today"
        title="Morning Brief"
        description="What changed for the symbols you hold or watch, from stored end-of-day data."
      />
      {!brief ? (
        <p className="text-sm text-negative" data-testid="brief-error">
          The brief could not be loaded just now.
        </p>
      ) : brief.symbols.length === 0 ? (
        <div data-testid="brief-empty">
          <PageEmptyState title="Nothing to Brief Yet">
            <p>
              Add symbols to a{" "}
              <Link href="/watchlist" className="underline">
                watchlist
              </Link>{" "}
              or hold a position, and they will show here.
            </p>
          </PageEmptyState>
        </div>
      ) : (
        <div className="grid gap-4 lg:grid-cols-2" data-testid="brief">
          <section className="rounded-xl border border-border bg-card p-4">
            <h2 className="mb-2 text-sm font-semibold">Largest Moves</h2>
            <ul className="space-y-1.5" data-testid="brief-moves">
              {brief.moves.map((m) => (
                <li key={m.ticker} className="flex items-baseline justify-between gap-2 text-sm">
                  <Link
                    href={`/stocks/${encodeURIComponent(m.ticker)}`}
                    className="ticker font-semibold"
                  >
                    {m.ticker}
                    {m.held ? (
                      <span className="ml-1 text-2xs font-normal text-text-tertiary">Held</span>
                    ) : null}
                  </Link>
                  <span className="text-2xs text-text-tertiary">
                    {formatCloseDate(m.previous_date)} → {formatCloseDate(m.close_date)}
                  </span>
                  <span
                    className={`font-mono ${m.change_pct > 0 ? "text-positive" : m.change_pct < 0 ? "text-negative" : ""}`}
                  >
                    {moveText(m.change_pct)}
                  </span>
                </li>
              ))}
            </ul>
            <p className="mt-2 text-2xs text-text-tertiary">{brief.note}</p>
          </section>
          <section className="rounded-xl border border-border bg-card p-4">
            <h2 className="mb-2 text-sm font-semibold">Alerts in the Last 24 Hours</h2>
            {brief.alerts.length ? (
              <ul className="space-y-1.5 text-sm" data-testid="brief-alerts">
                {brief.alerts.map((a) => (
                  <li key={`${a.title}-${a.created_at}`}>
                    {a.link ? (
                      <Link href={a.link} className="underline">
                        {a.title}
                      </Link>
                    ) : (
                      a.title
                    )}{" "}
                    <span className="text-2xs text-text-tertiary">
                      {formatUtcDateTime(a.created_at)}
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-xs text-text-secondary">None fired.</p>
            )}
          </section>
          <section className="rounded-xl border border-border bg-card p-4">
            <h2 className="mb-2 text-sm font-semibold">Earnings in the Next 7 Days</h2>
            {brief.earnings.length ? (
              <ul className="space-y-1 text-sm" data-testid="brief-earnings">
                {brief.earnings.map((e) => (
                  <li key={`${e.ticker}-${e.event_date}`}>
                    <span className="ticker font-semibold">{e.ticker}</span> ·{" "}
                    {formatCloseDate(e.event_date)}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-xs text-text-secondary">None stored.</p>
            )}
          </section>
          <section className="rounded-xl border border-border bg-card p-4">
            <h2 className="mb-2 text-sm font-semibold">New Documents (7 Days)</h2>
            {brief.documents.length ? (
              <ul className="space-y-1 text-sm" data-testid="brief-documents">
                {brief.documents.map((d) => (
                  <li key={d.id}>
                    <span className="ticker font-semibold">{d.ticker}</span> ·{" "}
                    <Link href={`/filings/${d.id}`} className="underline">
                      {d.title}
                    </Link>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-xs text-text-secondary">None stored.</p>
            )}
            <p className="mt-3 text-xs text-text-secondary" data-testid="brief-counts">
              <Link href="/portfolio?tab=journal" className="underline">
                {brief.open_plans} open plan{brief.open_plans === 1 ? "" : "s"}
              </Link>{" "}
              ·{" "}
              <Link href="/orders?status=pending" className="underline">
                {brief.pending_orders} pending order{brief.pending_orders === 1 ? "" : "s"}
              </Link>
            </p>
          </section>
        </div>
      )}
    </div>
  );
}
