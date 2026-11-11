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

import { ArrowRight, Layers, Play, Rewind, StepForward } from "lucide-react";
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
      "Screener, compare, signals and backtests run on the same stored daily history your paper trades fill against.",
    primary: { href: "/screener", label: "Open the screener" },
    secondary: { href: "/compare", label: "Compare symbols" },
    art: { kind: "phone", screen: "stock" },
    facts: [
      ["Screener", "Filter the tracked universe by the measures you care about."],
      ["Signals", "A seven-rule vote per symbol, shown line by line. Not investment advice."],
      ["Backtest", "Run a strategy over stored daily history and read the equity curve."],
    ],
    sections: (
      <>
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
    sections: <StatementBand />,
  },
];

export function findProductPage(slug: string): ProductPageSpec | undefined {
  return PRODUCT_PAGES.find((page) => page.slug === slug);
}

/** A replay player drawn from real stored bars, with the future hidden. */
async function ReplayArt() {
  const data = await loadPanel();
  if (!data || data.bars.length < 6) return null;
  const bars = data.bars.slice(-60);
  const step = Math.max(2, Math.floor(bars.length * 0.6));
  const visible = bars.slice(0, step).map((bar) => Number(bar.close));
  const min = Math.min(...visible);
  const max = Math.max(...visible);
  const span = max - min || 1;
  const width = 340;
  const height = 150;
  // Visible bars fill the left 62%; the rest of the axis is the hidden future.
  const plotWidth = width * 0.62;
  const points = visible
    .map((close, index) => {
      const x = 4 + (index / (visible.length - 1)) * (plotWidth - 8);
      const y = 10 + (1 - (close - min) / span) * (height - 20);
      return `${index ? "L" : "M"}${x.toFixed(1)} ${y.toFixed(1)}`;
    })
    .join(" ");

  return (
    <div
      aria-hidden
      className="dark grid w-full max-w-sm gap-3 rounded-3xl border border-border bg-card p-4 text-foreground shadow-2xl shadow-black/30"
    >
      <div className="flex justify-between gap-3 text-xs">
        <span className="ticker">{data.ticker} · Replay</span>
        <span className="font-mono text-text-tertiary">
          Bar {step} of {bars.length} · {formatCloseDate(bars[step - 1]?.ts)}
        </span>
      </div>
      <svg viewBox={`0 0 ${width} ${height}`} className="h-40 w-full" aria-hidden="true">
        <path d={points} fill="none" stroke="currentColor" strokeWidth="1.8" />
        <line
          x1={plotWidth}
          x2={plotWidth}
          y1="6"
          y2={height - 6}
          stroke="var(--border)"
          strokeDasharray="3 4"
        />
        <text x={plotWidth + 14} y={height / 2} fill="var(--text-tertiary)" fontSize="11">
          Future hidden
        </text>
      </svg>
      <div className="flex items-center justify-between gap-2">
        <div className="flex gap-2">
          <span className="grid size-9 place-items-center rounded-full border border-border-muted">
            <Rewind className="size-4" />
          </span>
          <span className="grid size-9 place-items-center rounded-full bg-primary text-primary-foreground">
            <Play className="size-4" />
          </span>
          <span className="grid size-9 place-items-center rounded-full border border-border-muted">
            <StepForward className="size-4" />
          </span>
        </div>
        <div className="flex gap-2 text-xs font-medium">
          <span className="rounded-full border border-border-muted px-3.5 py-2">Sell</span>
          <span className="rounded-full bg-primary px-3.5 py-2 text-primary-foreground">Buy</span>
        </div>
      </div>
    </div>
  );
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
            <span className="inline-flex w-max items-center gap-1.5 rounded-full border border-border-muted bg-surface-secondary px-3 py-1 text-xs text-text-secondary">
              <Layers className="size-3.5 text-brand" aria-hidden />
              {spec.name}
            </span>
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
              <span>
                <span className="block text-xs text-text-tertiary">{page.name}</span>
                <span className="block text-base font-medium">
                  {page.title} {page.soft}
                </span>
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
