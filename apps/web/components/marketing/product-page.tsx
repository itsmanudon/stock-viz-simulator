/**
 * Product pages (Aurora board v5): one page per part of the product, in the
 * landing page's style but shorter. Each is a hero with real-data artwork, a
 * row of three facts, then sections reused from the landing page.
 *
 * Every fact here was checked against the product as it is, not as planned:
 * both tickets review an order before placing it (the Replay ticket does
 * not), screens cannot
 * be saved yet, and news has no verification until the Aegis feed lands, so
 * there is no News page yet.
 */

import { ArrowRight } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import { loadPanel } from "@/components/marketing/hero-panel";
import { type PhoneScreenKey, loadPhoneScreens } from "@/components/marketing/hero-phone-screens";
import {
  FillSteps,
  LandingFaq,
  MovingToday,
  SessionTiles,
  StatementBand,
} from "@/components/marketing/landing-sections";
import { PhoneFrame } from "@/components/marketing/phone-frame";
import { ProofSection } from "@/components/marketing/proofs/proof-section";
import { ReplayPlayer } from "@/components/marketing/replay-player";
import { Button } from "@/components/ui/button";
import { formatCloseDate } from "@/lib/stock-workspace";

type LinkSpec = { href: string; label: string };

export type ProductPageSpec = {
  slug: string;
  name: string;
  title: string;
  soft: string;
  summary: string;
  primary: LinkSpec;
  secondary: LinkSpec;
  art: { kind: "phone"; screen: PhoneScreenKey } | { kind: "replay" };
  facts: [string, string][];
  sections: ReactNode;
};

export const PRODUCT_PAGES: ProductPageSpec[] = [
  {
    slug: "paper-trading",
    name: "Paper trading",
    title: "Trade the market",
    soft: "with money that isn’t real.",
    summary:
      "Market, limit, stop-loss and take-profit orders on stored end-of-day prices. Every order opens a review that shows the price, its date, the cost and the fill rule before anything goes through.",
    primary: { href: "/signup", label: "Open a paper account" },
    secondary: { href: "/markets", label: "Explore markets" },
    art: { kind: "phone", screen: "review" },
    facts: [
      [
        "Review before you place",
        "On the stock page and the trade ticket alike, the price, its date, the cost and the fill rule come first.",
      ],
      [
        "Stops and targets",
        "Protect a position with a stop loss or a take profit, checked after each weekday close.",
      ],
      [
        "US and Indian listings",
        "Each price in its own currency, converted for your account total.",
      ],
    ],
    sections: (
      <>
        <ProofSection only={["fill", "portfolio"]} />
        <FillSteps />
        <LandingFaq />
      </>
    ),
  },
  {
    slug: "research",
    name: "Research",
    title: "Find it, test it,",
    soft: "before you trade it.",
    summary:
      "Screener, compare, the checklist and backtests run on the same stored daily history your paper trades fill against.",
    primary: { href: "/screener", label: "Open the screener" },
    secondary: { href: "/compare", label: "Compare symbols" },
    art: { kind: "phone", screen: "stock" },
    facts: [
      ["Screener", "Filter the tracked universe by the measures you care about."],
      [
        "Checklist",
        "Six published conditions per symbol, each with its formula and evidence grade. Not investment advice.",
      ],
      ["Backtest", "Run a strategy over stored daily history and read the equity curve."],
    ],
    sections: (
      <>
        <ProofSection only={["backtest", "screener", "compare", "checklist", "chart"]} />
        <MovingToday />
        <SessionTiles />
      </>
    ),
  },
  {
    slug: "replay",
    name: "Replay",
    title: "Trade a past stretch",
    soft: "as if it were today.",
    summary:
      "Pick a stored date range, step through it bar by bar and trade without seeing what comes next. Then check every decision against what happened.",
    primary: { href: "/replay", label: "Start a replay" },
    secondary: { href: "/signup", label: "Create free account" },
    art: { kind: "replay" },
    facts: [
      ["Future-blind", "You only see bars up to the current step, never the ones after it."],
      [
        "Forensics",
        "The best and worst move after each fill, and the result against buy and hold.",
      ],
      ["Journal", "Notes lock at the first fill, so hindsight cannot rewrite them."],
    ],
    sections: (
      <>
        <ProofSection only={["replay"]} />
        <StatementBand />
      </>
    ),
  },
];

export function findProductPage(slug: string): ProductPageSpec | undefined {
  return PRODUCT_PAGES.find((page) => page.slug === slug);
}

/** A working replay player over real stored bars, the future hidden (`ReplayPlayer`). */
async function ReplayArt() {
  const data = await loadPanel();
  if (!data || data.bars.length < 6) return null;
  const bars = data.bars.slice(-60).map((bar) => ({
    close: Number(bar.close),
    date: formatCloseDate(bar.ts),
  }));
  return <ReplayPlayer ticker={data.ticker} bars={bars} />;
}

async function PhoneArt({ screen }: { screen: PhoneScreenKey }) {
  const screens = await loadPhoneScreens();
  const chosen = screens.find((candidate) => candidate.key === screen) ?? screens[0];
  return (
    <div aria-hidden className="dark text-foreground">
      <PhoneFrame screens={[chosen]} active={0} className="w-72" />
    </div>
  );
}

export function ProductPage({ spec }: { spec: ProductPageSpec }) {
  return (
    <>
      <section className="relative isolate overflow-hidden">
        <div className="mx-auto grid w-full max-w-6xl items-center gap-12 px-4 pt-14 pb-16 sm:px-6 sm:pt-20 lg:grid-cols-[1.05fr_0.95fr] lg:pb-24">
          <div
            aria-hidden
            className="brand-glow -top-10 right-0 -z-10 h-[30rem] w-[min(40rem,100%)] opacity-70"
          />
          <div className="grid gap-5">
            <h1
              data-motion="words"
              className="text-4xl font-medium tracking-[-0.035em] text-balance sm:text-6xl"
            >
              {spec.title} <span className="text-text-tertiary">{spec.soft}</span>
            </h1>
            <p className="max-w-xl text-lg leading-8 text-text-secondary text-pretty">
              {spec.summary}
            </p>
            <div className="flex flex-wrap gap-3">
              <Button asChild size="lg" className="rounded-full px-6">
                <Link href={spec.primary.href} className="gap-2">
                  {spec.primary.label}
                  <ArrowRight className="size-4" aria-hidden />
                </Link>
              </Button>
              <Button asChild size="lg" variant="outline" className="glass rounded-full px-6">
                <Link href={spec.secondary.href}>{spec.secondary.label}</Link>
              </Button>
            </div>
          </div>
          <div className="grid place-items-center">
            {spec.art.kind === "replay" ? <ReplayArt /> : <PhoneArt screen={spec.art.screen} />}
          </div>
        </div>
        <ul
          data-motion="rise"
          className="mx-auto grid w-full max-w-6xl gap-3 px-4 pb-8 sm:px-6 md:grid-cols-3"
        >
          {spec.facts.map(([title, body]) => (
            <li
              key={title}
              data-motion-item
              className="grid gap-1.5 rounded-2xl border border-border-muted bg-card p-5"
            >
              <h2 className="text-base font-medium">{title}</h2>
              <p className="text-sm leading-6 text-text-tertiary">{body}</p>
            </li>
          ))}
        </ul>
      </section>
      {spec.sections}
    </>
  );
}

/** Links to the other product pages, shown at the foot of each. */
export function OtherProductPages({ current }: { current: string }) {
  const others = PRODUCT_PAGES.filter((page) => page.slug !== current);
  return (
    <nav aria-label="More of StockViz" className="mx-auto w-full max-w-6xl px-4 pb-16 sm:px-6">
      <ul className="grid gap-3 sm:grid-cols-2">
        {others.map((page) => (
          <li key={page.slug}>
            <Link
              href={`/product/${page.slug}`}
              className="group flex items-center justify-between gap-4 rounded-2xl border border-border-muted bg-card px-5 py-4 transition-colors hover:border-border"
            >
              <span className="text-base font-medium">
                {page.title} {page.soft}
              </span>
              <ArrowRight
                className="size-4 shrink-0 text-text-tertiary transition-transform group-hover:translate-x-0.5"
                aria-hidden
              />
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  );
}
