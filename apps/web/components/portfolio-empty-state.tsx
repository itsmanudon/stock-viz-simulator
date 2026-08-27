import Link from "next/link";

import { formatCurrency } from "@/lib/portfolio-view-model";

export function PortfolioEmptyState({
  availableCash,
  displayCurrency,
}: {
  availableCash: string;
  displayCurrency: string;
}) {
  return (
    <section
      aria-labelledby="portfolio-empty-heading"
      className="border-y border-border-muted bg-surface-secondary/45 px-5 py-10 sm:px-8 sm:py-12"
    >
      <p className="text-xs font-medium uppercase tracking-[0.14em] text-brand">Start here</p>
      <h2 id="portfolio-empty-heading" className="mt-2 text-xl font-semibold tracking-tight">
        Your portfolio is ready
      </h2>
      <p className="mt-2 max-w-xl text-sm leading-6 text-muted-foreground">
        {formatCurrency(availableCash, displayCurrency)} available to invest. Explore the market,
        research a security, then place your first paper trade.
      </p>
      <div className="mt-6 flex flex-wrap gap-3">
        <Link
          href="/markets"
          className="inline-flex h-9 items-center rounded-md border border-border px-4 text-sm font-medium outline-none transition-colors hover:bg-surface-hover focus-visible:ring-2 focus-visible:ring-ring"
        >
          Explore markets
        </Link>
        <Link
          href="/trade"
          className="inline-flex h-9 items-center rounded-md bg-primary px-4 text-sm font-semibold text-primary-foreground outline-none transition-colors hover:bg-primary/90 focus-visible:ring-2 focus-visible:ring-ring"
        >
          Place a trade
        </Link>
      </div>
    </section>
  );
}
