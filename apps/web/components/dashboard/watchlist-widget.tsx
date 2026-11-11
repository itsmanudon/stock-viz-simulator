import Link from "next/link";

import { WidgetCard, WidgetEmpty } from "@/components/dashboard/widget-card";
import type { WatchlistItem } from "@/lib/api/watchlist";
import { formatNativePrice } from "@/lib/operational-trading";

/**
 * Compact read-only view of the watchlist; editing stays on /watchlist.
 * Prices in each symbol's own currency, as on /watchlist (UI audit T7: the
 * raw stored string "312.320000" showed here).
 */
export function WatchlistWidget({
  watchlist,
  currencies = {},
}: {
  watchlist: WatchlistItem[] | null;
  currencies?: Record<string, string>;
}) {
  const items = watchlist ?? [];

  return (
    <WidgetCard
      title="Watchlist"
      titleId="dashboard-watchlist-heading"
      action={items.length > 0 ? { label: "View all", href: "/watchlist" } : undefined}
    >
      {watchlist === null ? (
        <WidgetEmpty>The watchlist is unavailable right now.</WidgetEmpty>
      ) : items.length === 0 ? (
        <WidgetEmpty>
          Nothing tracked yet.{" "}
          <Link href="/markets" className="font-medium text-brand hover:underline">
            Browse markets
          </Link>
          .
        </WidgetEmpty>
      ) : (
        <ul className="-my-2 divide-y divide-border-muted">
          {items.slice(0, 5).map((item) => (
            <li key={item.ticker}>
              <Link
                href={`/stocks/${encodeURIComponent(item.ticker)}`}
                className="-mx-2 flex items-center justify-between gap-3 rounded-sm px-2 py-2 transition-colors hover:bg-surface-hover"
              >
                <span className="min-w-0">
                  <span className="block font-mono text-sm font-semibold">{item.ticker}</span>
                  <span className="mt-0.5 block truncate text-xs text-text-tertiary">
                    {item.name}
                  </span>
                </span>
                <span className="shrink-0 font-mono text-sm" data-financial>
                  {formatNativePrice(item.last_close, item.ticker, currencies)}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </WidgetCard>
  );
}
