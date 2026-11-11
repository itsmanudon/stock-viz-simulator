import { ArrowLeftRight, ArrowUpRight, ChartCandlestick, SearchCode, Users } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";

import { AlertsWidget } from "@/components/dashboard/alerts-widget";
import { AllocationWidget } from "@/components/dashboard/allocation-widget";
import { MoversWidget } from "@/components/dashboard/movers-widget";
import { OrdersWidget } from "@/components/dashboard/orders-widget";
import { PortfolioHero } from "@/components/dashboard/portfolio-hero";
import { WatchlistWidget } from "@/components/dashboard/watchlist-widget";
import { PageFrame } from "@/components/page-frame";
import { loadDashboardData } from "@/lib/dashboard-data";

export const metadata: Metadata = { title: "Dashboard" };

const SHORTCUTS = [
  { label: "Markets", href: "/markets", icon: ChartCandlestick },
  { label: "Research", href: "/compare", icon: SearchCode },
  { label: "Trade", href: "/trade", icon: ArrowLeftRight },
  { label: "Leaderboard", href: "/leaderboard", icon: Users },
] as const;

export default async function DashboardPage() {
  const { portfolio, history, analytics, orders, alerts, watchlist } = await loadDashboardData();
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
          <p className="text-xs font-medium tracking-[0.12em] text-text-secondary uppercase">
            StockViz workspace
          </p>
          <h1 className="mt-1.5 text-2xl font-medium tracking-tight sm:text-3xl">
            Today&rsquo;s position
          </h1>
        </div>
        <nav aria-label="Shortcuts" className="flex flex-wrap gap-2">
          {SHORTCUTS.map((shortcut) => {
            const Icon = shortcut.icon;
            return (
              <Link
                key={shortcut.href}
                href={shortcut.href}
                className="group inline-flex min-h-9 items-center gap-2 rounded-full border border-border-muted bg-card px-3.5 py-1.5 text-xs font-medium transition-colors hover:bg-surface-hover"
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
          open (orders, watchlist, alerts), then how the book moved. */}
      <div className="mt-6 grid gap-4">
        <PortfolioHero portfolio={portfolio} history={history} />
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          <OrdersWidget orders={orders} currencies={currencies} />
          <WatchlistWidget watchlist={watchlist} />
          <AlertsWidget alerts={alerts} />
        </div>
        <div className="grid gap-4 md:grid-cols-2">
          <MoversWidget analytics={analytics} />
          <AllocationWidget analytics={analytics} />
        </div>
      </div>
    </PageFrame>
  );
}
