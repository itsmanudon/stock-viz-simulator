import { ArrowLeftRight, ArrowUpRight, ChartCandlestick, SearchCode, Users } from "lucide-react";
import Link from "next/link";

import { AlertsWidget } from "@/components/dashboard/alerts-widget";
import { AllocationWidget } from "@/components/dashboard/allocation-widget";
import { MoversWidget } from "@/components/dashboard/movers-widget";
import { OrdersWidget } from "@/components/dashboard/orders-widget";
import { PortfolioHero } from "@/components/dashboard/portfolio-hero";
import { WatchlistWidget } from "@/components/dashboard/watchlist-widget";
import { PageFrame } from "@/components/page-frame";
import { loadDashboardData } from "@/lib/dashboard-data";

const SHORTCUTS = [
  { label: "Markets", href: "/markets", icon: ChartCandlestick },
  { label: "Research", href: "/compare", icon: SearchCode },
  { label: "Trade", href: "/trade", icon: ArrowLeftRight },
  { label: "Leaderboard", href: "/leaderboard", icon: Users },
] as const;

export default async function DashboardPage() {
  const { portfolio, history, analytics, orders, alerts, watchlist } = await loadDashboardData();
  const displayCurrency = portfolio.display_currency || "USD";

  return (
    <PageFrame width="workstation" className="py-6 lg:py-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="min-w-0">
          <p className="text-xs font-medium tracking-[0.12em] text-brand uppercase">
            StockViz workspace
          </p>
          <h1 className="mt-2 text-2xl font-semibold tracking-tight sm:text-3xl">
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
                className="group inline-flex items-center gap-2 rounded-full border border-border-muted bg-card px-3 py-1.5 text-xs font-medium transition-colors hover:bg-surface-hover"
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

      {/* Bento grid: hero spans two columns on wide screens, widgets fill in
          around it — the mixed-span mosaic from the Financial Dashboard file. */}
      <div className="mt-6 grid gap-4 lg:grid-cols-3 xl:grid-cols-4">
        <div className="lg:col-span-2 xl:col-span-3">
          <PortfolioHero portfolio={portfolio} history={history} />
        </div>
        <AlertsWidget alerts={alerts} />
        <MoversWidget analytics={analytics} />
        <OrdersWidget orders={orders} displayCurrency={displayCurrency} />
        <AllocationWidget analytics={analytics} />
        <WatchlistWidget watchlist={watchlist} />
      </div>
    </PageFrame>
  );
}
