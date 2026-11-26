import { BookLink as Link } from "@/components/book-link";
import {
  ArrowLeftRight,
  ArrowUpRight,
  BriefcaseBusiness,
  ChartCandlestick,
  SearchCode,
} from "lucide-react";
import type { Metadata } from "next";

import { AlertsWidget } from "@/components/dashboard/alerts-widget";
import { AllocationWidget } from "@/components/dashboard/allocation-widget";
import { MoversWidget } from "@/components/dashboard/movers-widget";
import { NewsWidget } from "@/components/dashboard/news-widget";
import { OrdersWidget } from "@/components/dashboard/orders-widget";
import { PortfolioHero } from "@/components/dashboard/portfolio-hero";
import { WatchlistWidget } from "@/components/dashboard/watchlist-widget";
import { PageFrame } from "@/components/page-frame";
import { MarketTerrain } from "@/components/prism/market-terrain";
import { loadTerrain } from "@/components/prism/terrain-data";
import { loadBookContext } from "@/lib/book-context";
import { loadDashboardData } from "@/lib/dashboard-data";

export const metadata: Metadata = { title: "Dashboard" };

const SHORTCUTS = [
  { label: "Markets", href: "/markets", icon: ChartCandlestick },
  { label: "Research", href: "/compare", icon: SearchCode },
  { label: "Trade", href: "/trade", icon: ArrowLeftRight },
  { label: "Portfolio", href: "/portfolio", icon: BriefcaseBusiness },
] as const;

export default async function DashboardPage({
  searchParams,
}: {
  searchParams: Promise<{ book?: string }>;
}) {
  const params = await searchParams;
  // A5.2: the hero and every widget follow `?book=<id|all>` (default when absent).
  const books = await loadBookContext(params.book, "/dashboard", params);
  const [{ portfolio, history, analytics, orders, alerts, watchlist, news, newsTickers }, terrain] =
    await Promise.all([loadDashboardData(books.book), loadTerrain()]);
  // Ticker to trading currency from what the page already holds, so pending
  // triggers show in their own currency without another request.
  const currencies: Record<string, string> = {};
  for (const item of [...portfolio.positions, ...(watchlist ?? [])]) {
    if (item.currency) currencies[item.ticker.toUpperCase()] = item.currency;
  }

  return (
    <PageFrame width="workstation" className="py-6 lg:py-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="min-w-0">
          <p className="text-xs font-medium tracking-[0.02em] text-text-secondary">
            StockViz Workspace
          </p>
          <h1 className="mt-1.5 text-3xl font-semibold tracking-[-0.035em] sm:text-4xl">
            Today&rsquo;s{" "}
            <span className="font-editorial text-prism pr-1 text-[1.08em]">position</span>
          </h1>
        </div>
        <nav aria-label="Shortcuts" className="flex flex-wrap gap-2">
          {SHORTCUTS.map((shortcut) => {
            const Icon = shortcut.icon;
            return (
              <Link
                key={shortcut.href}
                href={shortcut.href}
                className="spotlight group inline-flex min-h-9 items-center gap-2 rounded-full border border-border-muted bg-card/70 px-3.5 py-1.5 text-xs font-medium backdrop-blur transition-colors hover:bg-surface-hover"
              >
                <Icon className="size-3.5 text-text-tertiary" aria-hidden />
                {shortcut.label}
                <ArrowUpRight
                  className="size-3 text-text-tertiary transition-colors group-hover:text-brand"
                  aria-hidden
                />
              </Link>
            );
          })}
        </nav>
      </div>

      {/* Aurora board v3: the account hero takes the full width, then what is
          open (orders, watchlist, alerts), then how the book moved, then news
          on the symbols held or watched. */}
      <div className="mt-6 grid gap-4" data-stagger>
        <PortfolioHero
          portfolio={portfolio}
          history={history}
          book={
            books.isAll
              ? { name: "All books", kind: "all", count: books.books.length }
              : books.selected
                ? { name: books.selected.name, kind: books.selected.kind, count: 1 }
                : null
          }
        />
        {/* PRISM: the market as a 3D surface with time as its fourth axis.
            Drops out when fewer than four symbols share a full window. */}
        {terrain ? <MarketTerrain data={terrain} variant="compact" href="/markets" /> : null}
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          <OrdersWidget orders={orders} currencies={currencies} />
          <WatchlistWidget watchlist={watchlist} />
          <AlertsWidget alerts={alerts} />
        </div>
        <div className="grid gap-4 md:grid-cols-2">
          <MoversWidget analytics={analytics} />
          <AllocationWidget analytics={analytics} />
        </div>
        <NewsWidget news={news} tickers={newsTickers} />
      </div>
    </PageFrame>
  );
}
