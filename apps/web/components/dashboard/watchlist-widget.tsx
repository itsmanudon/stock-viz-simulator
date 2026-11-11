import Link from "next/link";

import { WidgetCard, WidgetEmpty } from "@/components/dashboard/widget-card";
import type { WatchlistItem } from "@/lib/api/watchlist";
import { formatCurrency } from "@/lib/portfolio-view-model";
import { formatCloseDate } from "@/lib/stock-workspace";

/**
 * Compact read-only view of the watchlist; editing stays on /watchlist.
 * Prices in each symbol's own currency, as on /watchlist (UI audit T7: the
 * raw stored string "312.320000" showed here), each dated by its own close
 * (audit RS-13). Rows carry their currency, so no symbol lookup is needed.
 */
export function WatchlistWidget({ watchlist }: { watchlist: WatchlistItem[] | null }) {
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
                <span className="shrink-0 text-right">
                  <span className="block font-mono text-sm" data-financial>
                    {formatCurrency(item.last_close, item.currency ?? "USD")}
                  </span>
                  {item.last_close !== null && formatCloseDate(item.last_close_at) ? (
                    <span className="mt-0.5 block text-2xs text-text-tertiary">
                      {formatCloseDate(item.last_close_at)}
                    </span>
                  ) : null}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </WidgetCard>
  );
}
