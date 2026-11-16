import Link from "next/link";

import { EquityCurve } from "@/components/equity-curve";
import { PaperCard } from "@/components/paper-card";
import { ValuationNotice } from "@/components/valuation-notice";
import type { Portfolio, PortfolioHistoryPoint } from "@/lib/api/trading";
import {
  PORTFOLIO_RANGES,
  type PortfolioRange,
  type PortfolioTab,
  buildPortfolioHref,
  calculateNavChange,
  formatCurrency,
  formatSignedPercent,
  splitMinorUnits,
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
  const currency = portfolio.display_currency || "USD";
  // The NAV history is in the base currency (Phase 4.8), not the display one.
  const navCurrency = portfolio.base_currency ?? "USD";
  const [major, minor] = splitMinorUnits(formatCurrency(portfolio.total_value, currency));
  const tone =
    change && change.percent > 0
      ? "text-positive"
      : change && change.percent < 0
        ? "text-negative"
        : "text-foreground";

  return (
    <section aria-labelledby="portfolio-heading" className="border-b border-border-muted pb-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-xs font-medium uppercase tracking-[0.16em] text-muted-foreground">
            Paper portfolio
          </p>
          <h1
            id="portfolio-heading"
            className="mt-1 text-2xl font-semibold tracking-[-0.025em] sm:text-3xl"
          >
            Portfolio
          </h1>
        </div>
        <Link
          href="/trade"
          className="inline-flex h-10 items-center rounded-full bg-primary px-5 text-sm font-semibold text-primary-foreground outline-none transition-colors hover:bg-primary/90 focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
        >
          Trade
        </Link>
      </div>

      {/* Aurora brand moment: the paper card over a soft glow beside the
          value. The chart and tables below stay calm, with no glow. */}
      <div className="mt-6 grid gap-6 md:grid-cols-[13rem_minmax(0,1fr)] md:items-center lg:grid-cols-[13rem_minmax(0,1fr)_auto] lg:items-end">
        <div className="relative isolate hidden md:block">
          <div aria-hidden className="brand-glow -top-10 -left-10 -z-10 h-56 w-80 opacity-70" />
          <PaperCard accountId={portfolio.portfolio_id} currency={currency} className="w-full" />
        </div>
        <div className="min-w-0">
          <p className="mb-1 flex items-center gap-2 text-xs text-muted-foreground">
            Portfolio value
            <span className="rounded-full border border-border-muted px-2 py-0.5 text-2xs">
              Simulated
            </span>
          </p>
          <p
            className="font-mono text-4xl font-medium tracking-[-0.04em] sm:text-5xl"
            data-financial
          >
            {major}
            {minor ? <span className="figure-minor">{minor}</span> : null}
          </p>
          <p className="mt-2 text-xs text-muted-foreground">
            Latest EOD valuation · Display currency {currency}
          </p>
          <ValuationNotice warnings={portfolio.valuation_warnings} className="mt-3 max-w-xl" />
        </div>

        {hasInvestments ? (
          <div className="lg:text-right">
            <p className="text-xs font-medium text-muted-foreground">
              {rangeLabel} {navCurrency} NAV change
            </p>
            {change ? (
              <div className={`mt-1 flex flex-wrap items-baseline gap-2 lg:justify-end ${tone}`}>
                <span className="sr-only">{direction}</span>
                <span className="font-mono text-lg font-semibold" data-financial>
                  {change.absolute > 0 ? "+" : ""}
                  {formatCurrency(change.absolute, navCurrency)}
                </span>
                <span className="font-mono text-sm" data-financial>
                  {formatSignedPercent(change.percent)}
                </span>
              </div>
            ) : (
              <p className="mt-1 font-mono text-lg text-muted-foreground">—</p>
            )}
            {latestDate ? (
              // The snapshot date is when the value was recorded; the value
              // itself uses each holding's latest stored close, which can be
              // much older. Side by side with "Last EOD" the two dates read as
              // a contradiction unless this says so (UI audit T8).
              <p className="mt-1 max-w-xs text-xs leading-5 text-muted-foreground lg:ml-auto">
                Snapshot recorded {formatDate(latestDate)}, valuing each holding at its latest
                stored close.
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
        <div className="mt-3 min-h-[220px] border-t border-border-muted pt-3">
          {history === null ? (
            <ChartMessage>Performance history is temporarily unavailable.</ChartMessage>
          ) : history.length < 2 || !change ? (
            <ChartMessage>
              Performance appears after two daily snapshots have been recorded.
            </ChartMessage>
          ) : (
            <EquityCurve
              points={history}
              currency={portfolio.base_currency || "USD"}
              accessibleLabel={`${rangeLabel} ${portfolio.base_currency || "USD"} NAV chart, ${change.percent >= 0 ? "up" : "down"} ${Math.abs(change.percent).toFixed(2)}% from ${formatDate(change.firstDate)} to ${formatDate(change.lastDate)}.`}
            />
          )}
        </div>
      ) : null}
    </section>
  );
}

function ChartMessage({ children }: { children: string }) {
  return (
    <div className="flex min-h-[220px] items-center justify-center text-center text-sm text-muted-foreground sm:min-h-[280px] lg:min-h-[320px]">
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
