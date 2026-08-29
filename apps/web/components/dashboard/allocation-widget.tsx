import { WidgetCard, WidgetEmpty } from "@/components/dashboard/widget-card";
import type { PortfolioAnalytics } from "@/lib/api/trading";
import { formatCurrency } from "@/lib/portfolio-view-model";

/**
 * Sector weights as a labelled bar list — the Dashboard UI reference's
 * "label / bar / value" row, which reads more precisely at small sizes than
 * the nested circles the Financial Dashboard file uses for the same data.
 */
export function AllocationWidget({ analytics }: { analytics: PortfolioAnalytics | null }) {
  const sectors = analytics?.sector_allocation ?? [];
  const currency = analytics?.display_currency || "USD";
  const largest = Math.max(...sectors.map((sector) => sector.pct), 1);

  return (
    <WidgetCard
      title="Sector allocation"
      titleId="dashboard-allocation-heading"
      action={sectors.length > 0 ? { label: "Analytics", href: "/portfolio" } : undefined}
    >
      {sectors.length === 0 ? (
        <WidgetEmpty>Allocation appears once you hold a position.</WidgetEmpty>
      ) : (
        <ul className="space-y-3">
          {sectors.slice(0, 5).map((sector) => (
            <li key={sector.sector}>
              <div className="flex items-baseline justify-between gap-3">
                <span className="min-w-0 truncate text-xs font-medium">{sector.sector}</span>
                <span className="shrink-0 font-mono text-xs text-text-secondary" data-financial>
                  {sector.pct.toFixed(1)}%
                </span>
              </div>
              <div
                className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-surface-secondary"
                role="img"
                aria-label={`${sector.sector}: ${sector.pct.toFixed(1)} percent, ${formatCurrency(
                  sector.market_value,
                  currency,
                )}`}
              >
                <div
                  className="h-full rounded-full bg-brand"
                  style={{ width: `${Math.max((sector.pct / largest) * 100, 2)}%` }}
                />
              </div>
            </li>
          ))}
        </ul>
      )}
    </WidgetCard>
  );
}
