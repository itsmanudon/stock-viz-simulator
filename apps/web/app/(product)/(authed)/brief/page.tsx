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
        <BriefBody brief={brief} />
      )}
    </div>
  );
}

const CARD = "rounded-xl border border-border-muted bg-card p-4 sm:p-5";

/**
 * Inside redesign (27 Nov 2026): the counts first as one strip of links,
 * the moves as a diverging bar chart in text (each bar's length is the move's
 * share of the largest move on the list), and the rest stacked beside it.
 * The two close dates are written once when every move shares them, else on
 * each row; nothing is dropped from the earlier four cards.
 */
function BriefBody({ brief }: { brief: MorningBrief }) {
  const largest = Math.max(...brief.moves.map((m) => Math.abs(m.change_pct)), 0);
  const firstMove = brief.moves[0];
  const sharedDates =
    firstMove &&
    brief.moves.every(
      (m) => m.previous_date === firstMove.previous_date && m.close_date === firstMove.close_date,
    );
  const counts = [
    { label: "Symbols", value: brief.symbols.length, href: "/watchlist" },
    { label: "Alerts, 24 hours", value: brief.alerts.length, href: "/notifications" },
    { label: "Earnings, 7 days", value: brief.earnings.length, href: "/earnings" },
    { label: "New documents", value: brief.documents.length, href: "/filings" },
  ];
  return (
    <div className="space-y-4" data-testid="brief">
      <dl className="grid grid-cols-2 overflow-hidden rounded-xl border border-border-muted bg-card sm:grid-cols-3 lg:grid-cols-6">
        {counts.map((c) => (
          <div key={c.label} className="border-border-muted border-b px-4 py-3 sm:border-r">
            <dt className="text-2xs font-medium text-text-tertiary">{c.label}</dt>
            <dd className="mt-0.5 font-mono text-lg font-semibold">
              <Link href={c.href} className="hover:text-brand">
                {c.value}
              </Link>
            </dd>
          </div>
        ))}
        <div className="border-border-muted border-b px-4 py-3 sm:border-r lg:border-r">
          <dt className="text-2xs font-medium text-text-tertiary">Open plans</dt>
          <dd className="mt-0.5 font-mono text-lg font-semibold">
            <Link href="/portfolio?tab=journal" className="hover:text-brand">
              {brief.open_plans}
            </Link>
          </dd>
        </div>
        <div className="border-border-muted border-b px-4 py-3">
          <dt className="text-2xs font-medium text-text-tertiary">Pending orders</dt>
          <dd className="mt-0.5 font-mono text-lg font-semibold">
            <Link href="/orders?status=pending" className="hover:text-brand">
              {brief.pending_orders}
            </Link>
          </dd>
        </div>
      </dl>
      <p className="sr-only" data-testid="brief-counts">
        {brief.open_plans} open plan{brief.open_plans === 1 ? "" : "s"} · {brief.pending_orders}{" "}
        pending order{brief.pending_orders === 1 ? "" : "s"}
      </p>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1.45fr)_minmax(0,1fr)]">
        <section className={CARD} aria-labelledby="brief-moves-heading">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h2 id="brief-moves-heading" className="text-sm font-semibold">
              Largest Moves
            </h2>
            {sharedDates && firstMove ? (
              <span className="font-mono text-2xs text-text-tertiary">
                {formatCloseDate(firstMove.previous_date)} → {formatCloseDate(firstMove.close_date)}
              </span>
            ) : null}
          </div>
          <ul className="mt-3 space-y-1" data-testid="brief-moves">
            {brief.moves.map((m) => {
              const share = largest > 0 ? Math.abs(m.change_pct) / largest : 0;
              const up = m.change_pct > 0;
              const down = m.change_pct < 0;
              return (
                <li
                  key={m.ticker}
                  className="grid grid-cols-[5.5rem_minmax(0,1fr)_4.5rem] items-center gap-3 rounded-md px-2 py-1.5 text-sm transition-colors hover:bg-surface-hover"
                >
                  <Link
                    href={`/stocks/${encodeURIComponent(m.ticker)}`}
                    className="ticker min-w-0 truncate font-semibold"
                  >
                    {m.ticker}
                    {m.held ? (
                      <span className="ml-1.5 rounded-full border border-border-muted px-1.5 py-px text-3xs font-normal text-text-tertiary">
                        Held
                      </span>
                    ) : null}
                  </Link>
                  <span className="min-w-0">
                    {/* Diverging bar: losses grow left from the centre, gains right. */}
                    <span aria-hidden className="relative block h-2">
                      <span className="absolute inset-y-0 left-1/2 w-px bg-border" />
                      <span
                        className={`brief-move-bar absolute inset-y-0 rounded-full ${
                          up ? "left-1/2 bg-positive/70" : down ? "right-1/2 bg-negative/70" : ""
                        }`}
                        style={{ width: `${(share * 50).toFixed(1)}%` }}
                        data-dir={up ? "up" : down ? "down" : "flat"}
                      />
                    </span>
                    {sharedDates ? null : (
                      <span className="mt-0.5 block truncate text-3xs text-text-tertiary">
                        {formatCloseDate(m.previous_date)} → {formatCloseDate(m.close_date)}
                      </span>
                    )}
                  </span>
                  <span
                    className={`text-right font-mono ${up ? "text-positive" : down ? "text-negative" : ""}`}
                  >
                    {moveText(m.change_pct)}
                  </span>
                </li>
              );
            })}
          </ul>
          <p className="mt-3 text-2xs leading-5 text-text-tertiary">{brief.note}</p>
        </section>

        <div className="grid content-start gap-4">
          <section className={CARD}>
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
              <p className="text-xs text-text-secondary">
                None fired.{" "}
                <Link href="/alerts" className="underline">
                  Manage alerts
                </Link>
              </p>
            )}
          </section>
          <section className={CARD}>
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
          <section className={CARD}>
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
          </section>
        </div>
      </div>
    </div>
  );
}
