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
import { listWatchlist } from "@/lib/api/watchlist";
import { currencyByTicker, dayMovePct, formatNativePrice } from "@/lib/operational-trading";
import { formatSignedPercent } from "@/lib/portfolio-view-model";
import { cn } from "@/lib/utils";

function fmtDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
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

  const currencies = currencyByTicker(universe);

  return (
    <PageFrame width="workstation" className="py-6 sm:py-8">
      <OperationalPageHeader
        eyebrow="Portfolio"
        title="Watchlist"
        description="Securities you are monitoring. Last close is the latest stored daily bar, not a live quote."
        meta={`${items.length} symbol${items.length === 1 ? "" : "s"}`}
      />
      <MonitoringSubnav current="/watchlist" />

      <div className="mt-6 border-y border-border-muted px-4 py-4 sm:border-x">
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
        <div className="mt-6 overflow-x-auto border-y border-border-muted">
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
                  Window
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
                      {formatNativePrice(item.last_close, item.ticker, currencies)}
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
      )}
    </PageFrame>
  );
}
