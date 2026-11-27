/**
 * Marketing hero, in the Aurora direction (SolCard's composition, board v5).
 *
 * Centred: the headline, its line and two pill buttons, with no small labels
 * or chips around them (owner, 27 Nov 2026). Below them, `HeroStage` shows the real-data product
 * panel with a phone in front that rotates through app screens, and on wide
 * screens pins while the paper card lifts out of the phone (option B).
 *
 * This file stays a server component: it fetches the data and builds the
 * markup, and hands it to the client stage. The constraints (end-of-day
 * data, simulated fills) are stated in the intro's paragraph; the phone and
 * pills are pictures, so nothing on them may be the only place a fact appears.
 */

import { ArrowRight, CalendarCheck, ShieldCheck, Wallet } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import Link from "next/link";

import { HeroPanel } from "@/components/marketing/hero-panel";
import { loadPhoneScreens } from "@/components/marketing/hero-phone-screens";
import { HeroStage } from "@/components/marketing/hero-stage";
import { loadBreadth } from "@/components/marketing/proofs/breadth";
import { LiquidChrome } from "@/components/prism/liquid-chrome";
import { Magnetic } from "@/components/prism/magnetic";
import { AmbientMood } from "@/components/sound/ambient-music";
import { Button } from "@/components/ui/button";

/**
 * Floating facts over the panel's chart area, from `lg` up: the chart has no
 * text there, so they never cover a figure. Each is true of the product.
 */
const STAGE_PILLS: { icon: LucideIcon; label: string; className: string }[] = [
  {
    icon: Wallet,
    label: "$100,000 paper balance",
    className: "top-34 left-[8%]",
  },
  {
    icon: CalendarCheck,
    label: "Every close dated",
    className: "top-50 left-[30%]",
  },
  {
    icon: ShieldCheck,
    label: "Fills at stored daily closes",
    className: "top-66 left-[12%]",
  },
];

export async function Hero() {
  const [screens, breadth] = await Promise.all([loadPhoneScreens(), loadBreadth()]);

  const lead = (
    <div className="mx-auto flex w-full max-w-4xl flex-col items-center px-4 pt-14 text-center sm:px-6 sm:pt-20 lg:pt-24">
      {/* Liquid Chrome (WebGL), its mid-tones tinted green or red by the session's
          breadth. Full-bleed: the hero copy is transformed by its entrance
          motion, which makes it this canvas's positioning box. */}
      <AmbientMood share={breadth?.share ?? null} />
      <LiquidChrome
        share={breadth?.share ?? null}
        className="-top-[68px] left-1/2 h-[calc(46rem+68px)] w-screen -translate-x-1/2"
      />
      <h1 className="text-5xl leading-[0.98] font-medium tracking-[-0.05em] text-balance sm:text-7xl lg:text-[6.5rem]">
        Learn the market <span className="font-editorial text-prism pr-1">without</span> risking the
        money
      </h1>

      <p className="mt-8 max-w-xl text-lg leading-8 text-text-secondary text-pretty">
        Screen it, backtest it, then trade it on paper — and keep score of what your decisions were
        actually worth.
      </p>

      <div className="mt-9 flex flex-wrap items-center justify-center gap-3">
        <Magnetic>
          <Button asChild size="lg" className="prism-cta h-12 rounded-full px-7 text-base">
            <Link href="/signup" className="gap-2">
              Create free account
              <ArrowRight className="size-4" aria-hidden />
            </Link>
          </Button>
        </Magnetic>
        <Magnetic strength={0.2}>
          <Button
            asChild
            size="lg"
            variant="outline"
            className="glass h-12 rounded-full px-7 text-base"
          >
            <Link href="/markets">Explore markets</Link>
          </Button>
        </Magnetic>
      </div>
    </div>
  );

  const pills = STAGE_PILLS.map((pill) => {
    const Icon = pill.icon;
    return (
      <span
        key={pill.label}
        className={`glass absolute z-20 inline-flex items-center gap-2 rounded-full px-3.5 py-2 text-sm text-foreground shadow-lg shadow-black/20 ${pill.className}`}
      >
        <Icon className="size-4 text-brand" />
        {pill.label}
      </span>
    );
  });

  const intro = (
    <div className="grid gap-4">
      <h2 className="text-3xl font-medium tracking-[-0.03em] text-balance sm:text-4xl">
        A broker is real money.{" "}
        <span className="text-text-tertiary">StockViz is the rehearsal.</span>
      </h2>
      <p className="max-w-lg text-base leading-7 text-text-secondary text-pretty">
        You get $100,000 that isn&rsquo;t real. Prices are stored end-of-day closes, and orders fill
        against them the way the order review tells you before you place one. Nothing reaches an
        exchange.
      </p>
      <div>
        <Button asChild size="lg" className="rounded-full px-6">
          <Link href="/signup">Open a paper account</Link>
        </Button>
      </div>
    </div>
  );

  return (
    <HeroStage lead={lead} panel={<HeroPanel />} pills={pills} screens={screens} intro={intro} />
  );
}
