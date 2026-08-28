import Link from "next/link";

import { DeltaPill } from "@/components/dashboard/delta-pill";
import { WidgetCard, WidgetEmpty } from "@/components/dashboard/widget-card";
import type { PortfolioAnalytics, TopMover } from "@/lib/api/trading";
import { formatSignedCurrency, formatSignedPercent } from "@/lib/portfolio-view-model";

/**
 * Best and worst performers in the user's own holdings, taken from
 * `/v1/portfolio/analytics`. Shows the top two of each so the widget stays a
 * glance rather than a table — the full list lives on the portfolio page.
 */
export function MoversWidget({ analytics }: { analytics: PortfolioAnalytics | null }) {
  const gainers = analytics?.top_gainers?.slice(0, 2) ?? [];
  const losers = analytics?.top_losers?.slice(0, 2) ?? [];
  const currency = analytics?.display_currency || "USD";
  const rows = [...gainers, ...losers];

  return (
    <WidgetCard
      title="Your movers"
      titleId="dashboard-movers-heading"
      action={{ label: "Portfolio", href: "/portfolio" }}
    >
      {rows.length === 0 ? (
        <WidgetEmpty>Open a position to see which holdings are moving.</WidgetEmpty>
      ) : (
        <ul className="-my-2 divide-y divide-border-muted">
          {rows.map((mover) => (
            <MoverRow key={mover.ticker} mover={mover} currency={currency} />
          ))}
        </ul>
      )}
    </WidgetCard>
  );
}

function MoverRow({ mover, currency }: { mover: TopMover; currency: string }) {
  return (
    <li>
      <Link
        href={`/stocks/${encodeURIComponent(mover.ticker)}`}
        className="-mx-2 flex items-center justify-between gap-3 rounded-sm px-2 py-2.5 transition-colors hover:bg-surface-hover"
      >
        <span className="min-w-0">
          <span className="block font-mono text-sm font-semibold">{mover.ticker}</span>
          <span className="mt-0.5 block truncate text-xs text-text-tertiary">{mover.name}</span>
        </span>
        <span className="flex shrink-0 flex-col items-end gap-1">
          <DeltaPill value={formatSignedPercent(mover.return_pct)} />
          <span className="font-mono text-2xs text-text-secondary" data-financial>
            {formatSignedCurrency(mover.unrealized_pl, currency)}
          </span>
        </span>
      </Link>
    </li>
  );
}
