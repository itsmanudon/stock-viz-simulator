import {
  ArrowLeftRight,
  ArrowUpRight,
  BriefcaseBusiness,
  ChartCandlestick,
  SearchCode,
  Users,
} from "lucide-react";
import Link from "next/link";

import { PageFrame } from "@/components/page-frame";

const DESTINATIONS = [
  {
    label: "Markets",
    href: "/markets",
    description: "Scan the tracked universe and daily movement.",
    icon: ChartCandlestick,
  },
  {
    label: "Research",
    href: "/compare",
    description: "Compare securities, inspect signals, and backtest rules.",
    icon: SearchCode,
  },
  {
    label: "Trade",
    href: "/trade",
    description: "Place simulated trades and review pending orders.",
    icon: ArrowLeftRight,
  },
  {
    label: "Portfolio",
    href: "/portfolio",
    description: "Track positions, performance, and watchlists.",
    icon: BriefcaseBusiness,
  },
  {
    label: "Community",
    href: "/leaderboard",
    description: "Compare public paper portfolios.",
    icon: Users,
  },
] as const;

export default function DashboardPage() {
  return (
    <PageFrame width="workstation" className="py-10 xl:py-12">
      <div className="max-w-3xl">
        <p className="text-xs font-medium tracking-[0.12em] text-brand uppercase">
          StockViz workspace
        </p>
        <h1 className="mt-3 text-3xl font-semibold tracking-tight sm:text-4xl">
          Your research workspace
        </h1>
        <p className="mt-3 max-w-2xl text-sm leading-6 text-text-secondary sm:text-base">
          Move from market discovery to investigation, simulated execution, and portfolio monitoring
          without losing context.
        </p>
      </div>

      <section className="mt-10 max-w-5xl border-y border-border-muted" aria-labelledby="start">
        <h2 id="start" className="sr-only">
          Start a workflow
        </h2>
        <div className="grid md:grid-cols-2">
          {DESTINATIONS.map((destination, index) => {
            const Icon = destination.icon;
            return (
              <Link
                key={destination.href}
                href={destination.href}
                className={`group flex min-h-28 items-start gap-4 border-border-muted px-1 py-6 transition-colors hover:bg-surface-hover focus-visible:z-10 sm:px-5 ${
                  index < DESTINATIONS.length - 1 ? "border-b" : ""
                } ${index % 2 === 0 ? "md:border-r" : ""} ${
                  index === DESTINATIONS.length - 1 ? "md:col-span-2 md:border-r-0" : ""
                }`}
              >
                <span className="mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-sm border border-border-muted bg-surface-secondary text-text-secondary">
                  <Icon className="size-4" aria-hidden />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="flex items-center justify-between gap-3 font-medium">
                    {destination.label}
                    <ArrowUpRight
                      className="size-4 text-text-tertiary transition-colors group-hover:text-brand"
                      aria-hidden
                    />
                  </span>
                  <span className="mt-1.5 block text-sm leading-5 text-text-secondary">
                    {destination.description}
                  </span>
                </span>
              </Link>
            );
          })}
        </div>
      </section>
    </PageFrame>
  );
}
