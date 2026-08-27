import Link from "next/link";

import type { PortfolioAnalytics, TopMover } from "@/lib/api/trading";
import {
  formatCurrency,
  formatSignedCurrency,
  formatSignedPercent,
} from "@/lib/portfolio-view-model";

const SECTOR_COLORS = [
  "bg-brand",
  "bg-sky-500",
  "bg-violet-500",
  "bg-cyan-500",
  "bg-slate-500",
  "bg-indigo-500",
  "bg-orange-400",
  "bg-fuchsia-500",
];

export function PortfolioInsights({
  analytics,
  hasEquityPositions,
}: {
  analytics: PortfolioAnalytics | null;
  hasEquityPositions: boolean;
}) {
  if (!hasEquityPositions) return null;

  if (analytics === null) {
    return (
      <section className="border-t border-border-muted py-8">
        <p className="text-sm text-muted-foreground">
          Portfolio insights are temporarily unavailable.
        </p>
      </section>
    );
  }

  const allocationLabel = `Equity sector allocation: ${analytics.sector_allocation
    .map((slice) => `${slice.sector} ${slice.pct.toFixed(1)}%`)
    .join(", ")}`;

  return (
    <section className="grid gap-10 border-t border-border-muted pt-8 lg:grid-cols-2">
      <div aria-labelledby="allocation-heading">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 id="allocation-heading" className="text-lg font-semibold tracking-tight">
            Equity sector allocation
          </h2>
          <p className="text-[11px] text-muted-foreground">Cash and options excluded</p>
        </div>

        <div
          role="img"
          aria-label={allocationLabel}
          className="mt-5 flex h-2.5 overflow-hidden rounded-sm bg-surface-secondary"
        >
          {analytics.sector_allocation.map((slice, index) => (
            <span
              key={slice.sector}
              aria-hidden="true"
              className={SECTOR_COLORS[index % SECTOR_COLORS.length]}
              style={{ width: `${Math.max(0, slice.pct)}%` }}
            />
          ))}
        </div>

        <dl className="mt-5 divide-y divide-border-muted border-y border-border-muted">
          {analytics.sector_allocation.map((slice, index) => (
            <div
              key={slice.sector}
              className="grid grid-cols-[1fr_auto_auto] items-center gap-4 py-2.5"
            >
              <dt className="flex min-w-0 items-center gap-2 text-sm">
                <span
                  aria-hidden="true"
                  className={`size-2 shrink-0 rounded-[2px] ${SECTOR_COLORS[index % SECTOR_COLORS.length]}`}
                />
                <span className="truncate">{slice.sector}</span>
              </dt>
              <dd className="font-mono text-xs text-muted-foreground" data-financial>
                {formatCurrency(slice.market_value, analytics.display_currency)}
              </dd>
              <dd className="w-14 text-right font-mono text-sm font-medium" data-financial>
                {slice.pct.toFixed(1)}%
              </dd>
            </div>
          ))}
        </dl>
      </div>

      <section aria-labelledby="movers-heading">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 id="movers-heading" className="text-lg font-semibold tracking-tight">
            Top movers
          </h2>
          <p className="text-[11px] text-muted-foreground">Position return, not attribution</p>
        </div>
        <div className="mt-5 grid gap-6 sm:grid-cols-2">
          <MoverList
            title="Gainers"
            movers={analytics.top_gainers}
            currency={analytics.display_currency}
            direction="gain"
          />
          <MoverList
            title="Detractors"
            movers={analytics.top_losers}
            currency={analytics.display_currency}
            direction="loss"
          />
        </div>
      </section>
    </section>
  );
}

function MoverList({
  title,
  movers,
  currency,
  direction,
}: {
  title: string;
  movers: TopMover[];
  currency: string;
  direction: "gain" | "loss";
}) {
  const tone = direction === "gain" ? "text-positive" : "text-negative";
  return (
    <section aria-labelledby={`movers-${direction}-heading`}>
      <h3
        id={`movers-${direction}-heading`}
        className="text-xs font-medium uppercase tracking-[0.12em] text-muted-foreground"
      >
        {title}
      </h3>
      {movers.length === 0 ? (
        <p className="mt-3 text-xs text-muted-foreground">
          {direction === "gain"
            ? "No positions are currently positive."
            : "No positions are currently negative."}
        </p>
      ) : (
        <ul className="mt-2 divide-y divide-border-muted border-y border-border-muted">
          {movers.slice(0, 5).map((mover) => (
            <li key={mover.ticker} className="grid grid-cols-[minmax(0,1fr)_auto] gap-4 py-2.5">
              <div className="min-w-0">
                <Link
                  href={`/stocks/${mover.ticker}`}
                  className="font-mono text-sm font-semibold hover:text-brand focus-visible:text-brand focus-visible:underline"
                >
                  {mover.ticker}
                </Link>
                <p className="truncate text-[11px] text-muted-foreground">{mover.name}</p>
              </div>
              <div className={`text-right font-mono ${tone}`} data-financial>
                <p className="text-sm font-medium">{formatSignedPercent(mover.return_pct)}</p>
                <p className="mt-0.5 text-[11px]">
                  {direction === "gain" ? "Gain" : "Loss"}{" "}
                  {formatSignedCurrency(mover.unrealized_pl, currency)}
                </p>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
