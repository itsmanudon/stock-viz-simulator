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

import { ByTheNumbers } from "@/components/marketing/by-the-numbers";
import { ClosingCta } from "@/components/marketing/closing-cta";
import { Hero } from "@/components/marketing/hero";
import { MarketTicker } from "@/components/marketing/market-ticker";
import { ProductTour } from "@/components/marketing/product-tour";
import { Reveal } from "@/components/marketing/reveal";
import { Button } from "@/components/ui/button";

/**
 * Marketing home.
 *
 * Copy here is deliberately literal about what the product is: end-of-day
 * data, simulated fills, rule-based signals. Overselling it as live trading
 * or AI advice would misrepresent the engine (see the repo's agent guides).
 *
 * The tour (`ProductTour`) demonstrates the four stages of a session with live
 * API data, so this file no longer restates them as a feature grid and a
 * separate "how it works" list. What is left here is the row of every surface
 * the tour doesn't stop at.
 */

const SURFACES: { icon: LucideIcon; label: string; href: string }[] = [
  { icon: ChartCandlestick, label: "Markets", href: "/markets" },
  { icon: ListFilter, label: "Screener", href: "/screener" },
  { icon: Signal, label: "Signals", href: "/recommendations" },
  { icon: FlaskConical, label: "Backtest", href: "/backtest" },
  { icon: ScrollText, label: "Paper trading", href: "/trade" },
  { icon: BriefcaseBusiness, label: "Portfolio", href: "/portfolio" },
];

export default function HomePage() {
  return (
    <div>
      <Hero />

      <MarketTicker />

      <ProductTour />

      <section
        aria-labelledby="surfaces-heading"
        className="border-y border-border-muted bg-surface-secondary/40"
      >
        <div className="mx-auto w-full max-w-6xl px-4 py-10 sm:px-6">
          <h2 id="surfaces-heading" className="sr-only">
            Everything in the workspace
          </h2>
          <ul className="flex flex-wrap items-center gap-x-6 gap-y-3">
            {SURFACES.map((surface) => (
              <li key={surface.href}>
                <Link
                  href={surface.href}
                  className="group flex items-center gap-2 text-sm text-text-secondary transition-colors hover:text-foreground"
                >
                  <surface.icon
                    className="size-4 text-text-tertiary transition-colors group-hover:text-brand"
                    aria-hidden
                  />
                  {surface.label}
                </Link>
              </li>
            ))}
          </ul>
        </div>
      </section>

      <ByTheNumbers />

      <ClosingCta />
    </div>
  );
}
