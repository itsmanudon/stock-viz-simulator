import {
  ArrowRight,
  BriefcaseBusiness,
  ChartCandlestick,
  FlaskConical,
  ListFilter,
  ScrollText,
  Signal,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import Link from "next/link";

import { TopMovers } from "@/components/top-movers";
import { Button } from "@/components/ui/button";

/**
 * Marketing home.
 *
 * Copy here is deliberately literal about what the product is: end-of-day
 * data, simulated fills, rule-based signals. Overselling it as live trading
 * or AI advice would misrepresent the engine (see the repo's agent guides).
 */

const FEATURES: { icon: LucideIcon; title: string; body: string; href: string }[] = [
  {
    icon: ChartCandlestick,
    title: "Markets at a glance",
    body: "Every tracked symbol with its latest close, day change, and a 30-day sparkline — sortable and filterable by sector.",
    href: "/markets",
  },
  {
    icon: ListFilter,
    title: "Screen on what matters",
    body: "Filter the universe by sector, RSI, momentum window, and proximity to the 52-week range. Filters combine with AND logic.",
    href: "/screener",
  },
  {
    icon: Signal,
    title: "Rule-based signals",
    body: "A transparent seven-vote rule set scores each symbol. Every vote is shown, so you can disagree with the ones you don't buy.",
    href: "/recommendations",
  },
  {
    icon: FlaskConical,
    title: "Backtest a thesis",
    body: "Run a strategy over historical bars and read the equity curve before you commit a single simulated dollar.",
    href: "/backtest",
  },
  {
    icon: ScrollText,
    title: "Paper trade for real",
    body: "Market, limit, stop-loss, and take-profit orders, plus options. Orders queue and fill against stored daily closes.",
    href: "/trade",
  },
  {
    icon: BriefcaseBusiness,
    title: "Track the outcome",
    body: "Positions, P&L, dividends, multi-currency FX, sector allocation, Sharpe, and drawdown — the scoreboard for your decisions.",
    href: "/portfolio",
  },
];

const STEPS = [
  {
    title: "Find something worth a look",
    body: "Start from the markets table or the screener, then open a symbol to read its chart, indicators, news, and sentiment in one place.",
  },
  {
    title: "Test the idea before you act",
    body: "Compare it against peers, check the signal votes, and backtest the rule you're actually considering.",
  },
  {
    title: "Trade it and keep score",
    body: "Place a paper order, set a price alert, and let the portfolio track what your decisions were worth.",
  },
];

export default function HomePage() {
  return (
    <div>
      <section className="mx-auto w-full max-w-7xl px-4 pt-16 pb-12 sm:px-6 sm:pt-24">
        <div className="mx-auto max-w-3xl text-center">
          <p className="text-2xs font-semibold tracking-[0.16em] text-brand uppercase">
            Paper trading · End-of-day data
          </p>
          <h1 className="mt-4 text-4xl font-semibold tracking-tight text-balance sm:text-5xl lg:text-6xl">
            Learn the market without risking the money
          </h1>
          <p className="mx-auto mt-6 max-w-2xl text-lg leading-8 text-text-secondary text-pretty">
            StockViz is a research and simulation workspace: screen and compare securities, backtest
            a strategy, then place paper orders and watch what your decisions were actually worth.
          </p>
          <div className="mt-9 flex flex-wrap items-center justify-center gap-3">
            <Button asChild size="lg">
              <Link href="/signup" className="gap-2">
                Create free account
                <ArrowRight className="size-4" aria-hidden />
              </Link>
            </Button>
            <Button asChild size="lg" variant="outline">
              <Link href="/markets">Explore markets</Link>
            </Button>
          </div>
          <p className="mt-5 text-xs text-text-tertiary">
            No card required. Simulated fills against stored daily closes — not a live brokerage.
          </p>
        </div>
      </section>

      <section aria-labelledby="movers-heading" className="mx-auto w-full max-w-5xl px-4 sm:px-6">
        <div className="mb-4 flex items-baseline justify-between gap-4">
          <h2 id="movers-heading" className="text-sm font-semibold">
            Today&rsquo;s movers
          </h2>
          <Link
            href="/markets"
            className="text-xs font-medium text-text-secondary transition-colors hover:text-brand"
          >
            See all markets →
          </Link>
        </div>
        <TopMovers />
      </section>

      <section
        aria-labelledby="features-heading"
        className="mx-auto w-full max-w-7xl px-4 py-20 sm:px-6 sm:py-28"
      >
        <div className="max-w-2xl">
          <p className="text-2xs font-semibold tracking-[0.16em] text-brand uppercase">
            What&rsquo;s inside
          </p>
          <h2
            id="features-heading"
            className="mt-3 text-3xl font-semibold tracking-tight text-balance sm:text-4xl"
          >
            The whole loop, not just the chart
          </h2>
        </div>

        <ul className="mt-12 grid gap-x-10 gap-y-10 sm:grid-cols-2 lg:grid-cols-3">
          {FEATURES.map((feature) => {
            const Icon = feature.icon;
            return (
              <li key={feature.href}>
                <Link href={feature.href} className="group block">
                  <span className="flex size-9 items-center justify-center rounded-md border border-border-muted bg-surface-secondary text-brand transition-colors group-hover:border-brand/40">
                    <Icon className="size-4" aria-hidden />
                  </span>
                  <h3 className="mt-4 flex items-center gap-1.5 font-medium">
                    {feature.title}
                    <ArrowRight
                      className="size-3.5 -translate-x-1 text-text-tertiary opacity-0 transition-all group-hover:translate-x-0 group-hover:text-brand group-hover:opacity-100"
                      aria-hidden
                    />
                  </h3>
                  <p className="mt-2 text-sm leading-6 text-text-secondary">{feature.body}</p>
                </Link>
              </li>
            );
          })}
        </ul>
      </section>

      <section
        aria-labelledby="how-heading"
        className="border-y border-border-muted bg-surface-secondary/40"
      >
        <div className="mx-auto w-full max-w-7xl px-4 py-20 sm:px-6 sm:py-24">
          <h2
            id="how-heading"
            className="max-w-2xl text-3xl font-semibold tracking-tight text-balance sm:text-4xl"
          >
            How a session usually goes
          </h2>
          <ol className="mt-12 grid gap-10 lg:grid-cols-3">
            {STEPS.map((step, index) => (
              <li key={step.title} className="border-t border-border-muted pt-5">
                <span className="font-mono text-xs font-semibold text-brand">
                  {String(index + 1).padStart(2, "0")}
                </span>
                <h3 className="mt-2 font-medium">{step.title}</h3>
                <p className="mt-2 text-sm leading-6 text-text-secondary">{step.body}</p>
              </li>
            ))}
          </ol>
        </div>
      </section>

      <section className="mx-auto w-full max-w-7xl px-4 py-20 sm:px-6 sm:py-28">
        <div className="mx-auto max-w-2xl text-center">
          <h2 className="text-3xl font-semibold tracking-tight text-balance sm:text-4xl">
            Start with $100,000 that isn&rsquo;t real
          </h2>
          <p className="mt-4 text-base leading-7 text-text-secondary text-pretty">
            Make the expensive mistakes here instead. Your portfolio, orders, and alerts are saved
            to your account.
          </p>
          <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
            <Button asChild size="lg">
              <Link href="/signup" className="gap-2">
                Create free account
                <ArrowRight className="size-4" aria-hidden />
              </Link>
            </Button>
            <Button asChild size="lg" variant="outline">
              <Link href="/leaderboard">See the leaderboard</Link>
            </Button>
          </div>
        </div>
      </section>
    </div>
  );
}
