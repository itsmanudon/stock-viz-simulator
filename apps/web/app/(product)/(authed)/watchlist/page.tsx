/**
 * /watchlist — monitoring list of securities the user cares about.
 *
 * Server-rendered snapshot rows. Add/remove and row actions are client islands.
 * Watchlist stays under Portfolio; this is not an order blotter.
 */

import Link from "next/link";

import {
  MonitoringSubnav,
  OperationalEmptyState,
  OperationalPageHeader,
} from "@/components/operational-page-header";
import { PageFrame } from "@/components/page-frame";
import { Sparkline } from "@/components/sparkline";
import { AddWatchlistForm, WatchlistRowActions } from "@/components/watchlist-controls";
import { getBars, listSymbols } from "@/lib/api";
import { parseApiTimestamp } from "@/lib/api-time";
import { listWatchlist } from "@/lib/api/watchlist";
import { dayMovePct } from "@/lib/operational-trading";
import { formatCurrency, formatSignedPercent } from "@/lib/portfolio-view-model";
import { formatCloseDate } from "@/lib/stock-workspace";
import { cn } from "@/lib/utils";

function fmtDate(iso: string): string {
  return parseApiTimestamp(iso).toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

/** The close's own date (audit RS-13): symbols end on different days. */
function closeLabel(close: string | null, at: string | null | undefined): string {
  if (close === null) return "No stored close";
  return formatCloseDate(at) ?? "Date unknown";
}

export default async function WatchlistPage() {
  const [items, universe] = await Promise.all([listWatchlist(), listSymbols().catch(() => [])]);
  const listed = new Set(items.map((item) => item.ticker));
  const addable = universe
    .filter((symbol) => !listed.has(symbol.ticker))
    .sort((a, b) => a.ticker.localeCompare(b.ticker))
    .map((symbol) => ({ ticker: symbol.ticker, name: symbol.name }));

  const sparklines = await Promise.all(
    items.map((item) =>
      getBars(item.ticker, { limit: 30 })
        .then((bars) => bars.map((bar) => Number(bar.close)))
        .catch(() => [] as number[]),
    ),
  );

  return (
    <PageFrame width="workstation" className="py-5 sm:py-7">
      <OperationalPageHeader
        eyebrow="Portfolio"
        title="Watchlist"
        description="Securities you are monitoring. Last close is the latest stored daily bar, not a live quote."
        meta={`${items.length} symbol${items.length === 1 ? "" : "s"}`}
      />
      <MonitoringSubnav current="/watchlist" />

      <div className="mt-5 rounded-md border border-border-muted bg-card px-4 py-4">
        <AddWatchlistForm symbols={addable} />
      </div>

      {items.length === 0 ? (
        <div className="mt-6">
          <OperationalEmptyState
            title="Nothing on this list yet"
            action={
              <Link href="/markets" className="text-sm hover:underline">
                Discover symbols in Markets
              </Link>
            }
          >
            <p>
              Add a ticker above, or star one from a stock workspace. From here you can research,
              trade, or create a price alert.
            </p>
          </OperationalEmptyState>
        </div>
      ) : (
        <>
          {/* Cards under md, where the table scrolled sideways (audit P1). */}
          <ul aria-label="Watched securities" className="mt-5 grid gap-3 md:hidden">
            {items.map((item, index) => {
              const closes = sparklines[index] ?? [];
              const move = dayMovePct(closes[0], closes[closes.length - 1]);
              return (
                <li
                  key={item.ticker}
                  className="grid gap-3 rounded-2xl border border-border-muted bg-card p-4"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <Link
                        href={`/stocks/${item.ticker}`}
                        className="font-mono text-base font-medium hover:underline"
                      >
                        {item.ticker}
                      </Link>
                      <p className="truncate text-xs text-text-tertiary">
                        {item.name}
                        {item.sector ? ` · ${item.sector}` : ""}
                      </p>
                    </div>
                    <div className="text-right">
                      <p className="font-mono text-sm" data-financial>
                        {formatCurrency(item.last_close, item.currency ?? "USD")}
                      </p>
                      <p className="text-2xs text-text-tertiary">
                        {closeLabel(item.last_close, item.last_close_at)}
                      </p>
                      <p
                        className={cn(
                          "font-mono text-xs",
                          move !== null && move > 0 && "text-positive",
                          move !== null && move < 0 && "text-negative",
                        )}
                        data-financial
                      >
                        {formatSignedPercent(move)} · 30 days
                      </p>
                    </div>
                  </div>
                  <Sparkline closes={closes} className="h-10 w-full" />
                  <div className="flex items-center justify-between gap-3 border-t border-border-muted pt-3">
                    <span className="text-xs text-text-tertiary">
                      Added {fmtDate(item.added_at)}
                    </span>
                    <WatchlistRowActions ticker={item.ticker} />
                  </div>
                </li>
              );
            })}
          </ul>
          <div className="mt-5 hidden overflow-x-auto rounded-md border border-border-muted bg-card md:block">
            <table className="w-full min-w-[44rem] text-sm">
              <caption className="sr-only">Watched securities</caption>
              <thead>
                <tr className="border-b border-border-muted text-left text-3xs font-semibold tracking-[0.12em] text-text-tertiary uppercase">
                  <th scope="col" className="px-3 py-2.5">
                    Ticker
                  </th>
                  <th scope="col" className="px-3 py-2.5">
                    Name
                  </th>
                  <th scope="col" className="hidden px-3 py-2.5 md:table-cell">
                    Sector
                  </th>
                  <th scope="col" className="px-3 py-2.5 text-right">
                    Last close
                  </th>
                  <th scope="col" className="px-3 py-2.5 text-right">
                    30-day change
                  </th>
                  <th scope="col" className="hidden w-[7.5rem] px-3 py-2.5 lg:table-cell">
                    30-day
                  </th>
                  <th scope="col" className="hidden px-3 py-2.5 sm:table-cell">
                    Added
                  </th>
                  <th scope="col" className="px-3 py-2.5 text-right">
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {items.map((item, index) => {
                  const closes = sparklines[index] ?? [];
                  const move = dayMovePct(closes[0], closes[closes.length - 1]);
                  return (
                    <tr key={item.ticker} className="border-b border-border-muted last:border-0">
                      <td className="px-3 py-3 font-mono font-medium">
                        <Link href={`/stocks/${item.ticker}`} className="hover:underline">
                          {item.ticker}
                        </Link>
                      </td>
                      <td className="truncate px-3 py-3 text-text-secondary">{item.name}</td>
                      <td className="hidden px-3 py-3 text-text-tertiary md:table-cell">
                        {item.sector ?? "—"}
                      </td>
                      <td className="px-3 py-3 text-right font-mono">
                        {formatCurrency(item.last_close, item.currency ?? "USD")}
                        <span className="block font-sans text-2xs text-text-tertiary">
                          {closeLabel(item.last_close, item.last_close_at)}
                        </span>
                      </td>
                      <td
                        className={cn(
                          "px-3 py-3 text-right font-mono",
                          move !== null && move > 0 && "text-positive",
                          move !== null && move < 0 && "text-negative",
                        )}
                      >
                        {formatSignedPercent(move)}
                      </td>
                      <td className="hidden px-3 py-3 lg:table-cell">
                        <Sparkline closes={closes} />
                      </td>
                      <td className="hidden px-3 py-3 text-xs text-text-tertiary sm:table-cell">
                        {fmtDate(item.added_at)}
                      </td>
                      <td className="px-3 py-3 text-right">
                        <WatchlistRowActions ticker={item.ticker} />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      )}
    </PageFrame>
  );
}
