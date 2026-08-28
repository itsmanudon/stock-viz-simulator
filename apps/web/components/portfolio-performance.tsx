import Link from "next/link";

import { EquityCurve } from "@/components/equity-curve";
import type { Portfolio, PortfolioHistoryPoint } from "@/lib/api/trading";
import {
  PORTFOLIO_RANGES,
  type PortfolioRange,
  type PortfolioTab,
  buildPortfolioHref,
  calculateNavChange,
  formatCurrency,
  formatSignedPercent,
} from "@/lib/portfolio-view-model";

type Props = {
  portfolio: Portfolio;
  history: PortfolioHistoryPoint[] | null;
  range: PortfolioRange;
  tab: PortfolioTab;
};

export function PortfolioPerformance({ portfolio, history, range, tab }: Props) {
  const hasInvestments = portfolio.positions.length > 0 || portfolio.option_positions.length > 0;
  const change = hasInvestments && history ? calculateNavChange(history) : null;
  const rangeLabel = PORTFOLIO_RANGES.find((item) => item.value === range)?.label ?? "3M";
  const latestDate = history?.at(-1)?.date ?? null;
  const direction = change && change.percent < 0 ? "Loss" : "Gain";
  const tone =
    change && change.percent > 0
      ? "text-positive"
      : change && change.percent < 0
        ? "text-negative"
        : "text-foreground";

  return (
    <section aria-labelledby="portfolio-heading" className="border-b border-border-muted pb-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-xs font-medium uppercase tracking-[0.16em] text-muted-foreground">
            Paper portfolio
          </p>
          <h1 id="portfolio-heading" className="mt-1 text-2xl font-bold tracking-tight">
            Portfolio
          </h1>
        </div>
        <Link
          href="/trade"
          className="inline-flex h-9 items-center rounded-md bg-primary px-4 text-sm font-semibold text-primary-foreground outline-none transition-colors hover:bg-primary/90 focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
        >
          Trade
        </Link>
      </div>

      <div className="mt-7 grid gap-5 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-end">
        <div className="min-w-0">
          <p className="font-mono text-4xl font-bold tracking-[-0.04em] sm:text-5xl" data-financial>
            {formatCurrency(portfolio.total_value, portfolio.display_currency || "USD")}
          </p>
          <p className="mt-2 text-xs text-muted-foreground">
            Latest EOD valuation · Display currency {portfolio.display_currency || "USD"}
          </p>
        </div>

        {hasInvestments ? (
          <div className="lg:text-right">
            <p className="text-xs font-medium text-muted-foreground">{rangeLabel} USD NAV change</p>
            {change ? (
              <div className={`mt-1 flex flex-wrap items-baseline gap-2 lg:justify-end ${tone}`}>
                <span className="sr-only">{direction}</span>
                <span className="font-mono text-lg font-semibold" data-financial>
                  {change.absolute > 0 ? "+" : ""}
                  {formatCurrency(change.absolute, "USD")}
                </span>
                <span className="font-mono text-sm" data-financial>
                  {formatSignedPercent(change.percent)}
                </span>
              </div>
            ) : (
              <p className="mt-1 font-mono text-lg text-muted-foreground">—</p>
            )}
            {latestDate ? (
              <p className="mt-1 text-xs text-muted-foreground">
                Snapshot through {formatDate(latestDate)}
              </p>
            ) : null}
          </div>
        ) : null}
      </div>

      {hasInvestments ? (
        <nav aria-label="Performance range" className="mt-6 flex items-center gap-1">
          {PORTFOLIO_RANGES.map((item) => {
            const selected = item.value === range;
            return (
              <Link
                key={item.value}
                href={buildPortfolioHref({ range: item.value, tab })}
                aria-current={selected ? "true" : undefined}
                className={`inline-flex h-8 min-w-10 items-center justify-center rounded-md px-2.5 text-xs font-medium outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring ${
                  selected
                    ? "bg-brand-muted text-brand"
                    : "text-muted-foreground hover:bg-surface-hover hover:text-foreground"
                }`}
              >
                {item.label}
              </Link>
            );
          })}
        </nav>
      ) : null}

      {hasInvestments ? (
        <div className="mt-4 min-h-[240px] border-t border-border-muted pt-4">
          {history === null ? (
            <ChartMessage>Performance history is temporarily unavailable.</ChartMessage>
          ) : history.length < 2 || !change ? (
            <ChartMessage>
              Performance appears after two daily snapshots have been recorded.
            </ChartMessage>
          ) : (
            <EquityCurve
              points={history}
              accessibleLabel={`${rangeLabel} USD NAV chart, ${change.percent >= 0 ? "up" : "down"} ${Math.abs(change.percent).toFixed(2)}% from ${formatDate(change.firstDate)} to ${formatDate(change.lastDate)}.`}
            />
          )}
        </div>
      ) : null}
    </section>
  );
}

function ChartMessage({ children }: { children: string }) {
  return (
    <div className="flex min-h-[240px] items-center justify-center text-center text-sm text-muted-foreground sm:min-h-[300px] lg:min-h-[340px]">
      <p className="max-w-md">{children}</p>
    </div>
  );
}

function formatDate(date: string): string {
  return new Date(`${date}T00:00:00Z`).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  });
}
