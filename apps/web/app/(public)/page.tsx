import {
  ArrowRight,
  BriefcaseBusiness,
  ChartCandlestick,
  FlaskConical,
  ListChecks,
  ListFilter,
  ScrollText,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import Link from "next/link";

import { ClosingCta } from "@/components/marketing/closing-cta";
import { Hero } from "@/components/marketing/hero";
import { LandingMotion } from "@/components/marketing/landing-motion";
import {
  FillSteps,
  LandingFaq,
  MovingToday,
  SessionTiles,
  StatementBand,
  StorySection,
} from "@/components/marketing/landing-sections";
import { ProofSection } from "@/components/marketing/proofs/proof-section";
import { KineticMarquee } from "@/components/prism/kinetic-marquee";
import { TerrainSection } from "@/components/prism/terrain-section";

/**
 * Marketing home.
 *
 * Copy here is deliberately literal about what the product is: end-of-day
 * data, simulated fills, a rule-based checklist. Overselling it as live trading
 * or AI advice would misrepresent the engine (see the repo's agent guides).
 *
 * Section order follows the approved Aurora board (v5): hero with the pinned
 * card, movers, how a session works, "watch it work" (one animated row per
 * feature, motion batch 1), the scroll story, every fill shows its
 * work, the statement band, rankings, the workspace tiles, FAQ, closing call
 * to action. The old ticker strip, product tour and numbers band fold into
 * those sections. The workspace tiles stay because they link every surface;
 * each line describes what the surface does today, nothing it does not.
 */

const SURFACES: {
  icon: LucideIcon;
  label: string;
  href: string;
  lead: string;
  detail: string;
}[] = [
  {
    icon: ChartCandlestick,
    label: "Markets",
    href: "/markets",
    lead: "Every tracked symbol.",
    detail: "Latest stored close and daily change, sortable.",
  },
  {
    icon: ListFilter,
    label: "Screener",
    href: "/screener",
    lead: "Narrow the universe.",
    detail: "Filter tracked symbols by the metrics you care about.",
  },
  {
    icon: ListChecks,
    label: "Checklist",
    href: "/checklist",
    lead: "Six published conditions.",
    detail: "Each with its formula and evidence grade, per symbol. Not investment advice.",
  },
  {
    icon: FlaskConical,
    label: "Backtest",
    href: "/backtest",
    lead: "Test before you trade.",
    detail: "Run a strategy over stored daily history and read the equity curve.",
  },
  {
    icon: ScrollText,
    label: "Paper trading",
    href: "/trade",
    lead: "$100,000 to practise with.",
    detail: "Market and limit orders, filled at stored daily closes.",
  },
  {
    icon: BriefcaseBusiness,
    label: "Portfolio",
    href: "/portfolio",
    lead: "Keep score.",
    detail: "Positions, value history, dividends and a trading journal.",
  },
];

export default function HomePage() {
  return (
    <div>
      <Hero />

      <TerrainSection />

      <LandingMotion>
        <MovingToday />
        <SessionTiles />
        <ProofSection />
        <StorySection />
        <FillSteps />
        <StatementBand />
        <KineticMarquee />

        <section aria-labelledby="surfaces-heading" className="border-y border-border-muted">
          <div className="mx-auto w-full max-w-6xl px-4 py-14 sm:px-6 sm:py-20">
            <h2
              id="surfaces-heading"
              className="text-2xl font-medium tracking-[-0.02em] text-balance sm:text-3xl"
            >
              Everything in the workspace
            </h2>
            {/* A sideways-scrolling row of tiles. The row scrolls inside its own
              box, so the page itself never scrolls horizontally. */}
            <ul className="mt-8 grid snap-x snap-mandatory auto-cols-[minmax(15rem,1fr)] grid-flow-col gap-3 overflow-x-auto pb-3">
              {SURFACES.map((surface) => (
                <li
                  key={surface.href}
                  className="spotlight group relative flex min-h-56 snap-start flex-col gap-4 overflow-hidden rounded-2xl border border-border-muted bg-linear-to-b from-card to-background p-5 transition-[border-color,transform] duration-300 focus-within:ring-2 focus-within:ring-ring hover:-translate-y-1 hover:border-border"
                >
                  <span className="grid size-10 place-items-center rounded-full border border-border-muted bg-surface-secondary">
                    <surface.icon className="size-4 text-brand" aria-hidden />
                  </span>
                  <p className="text-base leading-6 text-text-tertiary text-pretty">
                    <span className="font-medium text-foreground">{surface.lead}</span>{" "}
                    {surface.detail}
                  </p>
                  {/* The title is the link; its ::after stretches over the whole
                    tile so the tile is one target with a short accessible name. */}
                  <Link
                    href={surface.href}
                    className="mt-auto inline-flex items-center gap-1.5 text-sm font-medium text-text-secondary transition-colors after:absolute after:inset-0 after:rounded-2xl group-hover:text-foreground focus-visible:outline-none"
                  >
                    {surface.label}
                    <ArrowRight
                      className="size-3.5 transition-transform group-hover:translate-x-0.5"
                      aria-hidden
                    />
                  </Link>
                  <span
                    aria-hidden
                    className="brand-glow -right-16 -bottom-20 -z-10 size-44 opacity-0 transition-opacity group-hover:opacity-60"
                  />
                </li>
              ))}
            </ul>
          </div>
        </section>

        <LandingFaq />
      </LandingMotion>

      <ClosingCta />
    </div>
  );
}
