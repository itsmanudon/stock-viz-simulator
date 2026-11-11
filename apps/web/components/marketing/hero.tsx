/**
 * Marketing hero, in the Aurora direction (SolCard's composition, board v5).
 *
 * Centred: a glass badge, the headline, two pill buttons and the honest
 * constraints as chips. Below them, `HeroStage` shows the real-data product
 * panel with a phone in front that rotates through app screens, and on wide
 * screens pins while the paper card lifts out of the phone (option B).
 *
 * This file stays a server component: it fetches the data and builds the
 * markup, and hands it to the client stage. The constraints (end-of-day
 * data, simulated fills) stay in the chips as text; the phone and pills are
 * pictures, so nothing on them may be the only place a fact appears.
 */

import {
  ArrowRight,
  CalendarCheck,
  Check,
  Database,
  ShieldCheck,
  Sparkles,
  Wallet,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import Link from "next/link";

import { HeroPanel } from "@/components/marketing/hero-panel";
import { loadPhoneScreens } from "@/components/marketing/hero-phone-screens";
import { HeroStage } from "@/components/marketing/hero-stage";
import { Button } from "@/components/ui/button";
import { listSymbols } from "@/lib/api";

/**
 * Real count or nothing. A hardcoded "500+" would be the exact kind of
 * invented proof the repo's guides rule out.
 */
async function symbolCount(): Promise<number | null> {
  try {
    return (await listSymbols()).length;
  } catch {
    return null;
  }
}

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
  const [count, screens] = await Promise.all([symbolCount(), loadPhoneScreens()]);

  const chips: { icon: LucideIcon; label: string }[] = [
    { icon: Check, label: "No card required" },
    ...(count ? [{ icon: Database, label: `${count} symbols tracked` }] : []),
    { icon: ShieldCheck, label: "Simulated fills · EOD data" },
  ];

  const lead = (
    <div className="mx-auto flex w-full max-w-4xl flex-col items-center px-4 pt-14 text-center sm:px-6 sm:pt-20 lg:pt-24">
      <Link
        href="/trade"
        className="glass inline-flex items-center gap-2 rounded-full py-1 pr-2.5 pl-3 font-mono text-2xs tracking-[0.12em] text-text-secondary uppercase transition-colors hover:text-foreground"
      >
        Options settlement
        <ArrowRight className="size-3" aria-hidden />
      </Link>

      <h1 className="mt-6 text-4xl font-medium tracking-[-0.035em] text-balance sm:text-6xl lg:text-7xl">
        Learn the market <span className="text-brand-gradient">without risking the money</span>
      </h1>

      <p className="mt-6 max-w-xl text-lg leading-8 text-text-secondary text-pretty">
        Screen it, backtest it, then trade it on paper — and keep score of what your decisions were
        actually worth.
      </p>

      <div className="mt-9 flex flex-wrap items-center justify-center gap-3">
        <Button asChild size="lg" className="rounded-full px-6">
          <Link href="/signup" className="gap-2">
            Create free account
            <ArrowRight className="size-4" aria-hidden />
          </Link>
        </Button>
        <Button asChild size="lg" variant="outline" className="glass rounded-full px-6">
          <Link href="/markets">Explore markets</Link>
        </Button>
      </div>

      <ul className="mt-8 flex flex-wrap items-center justify-center gap-x-5 gap-y-2.5">
        {chips.map((chip) => {
          const Icon = chip.icon;
          return (
            <li
              key={chip.label}
              className="flex items-center gap-1.5 font-mono text-2xs text-text-tertiary"
            >
              <Icon className="size-3.5 text-brand" aria-hidden />
              {chip.label}
            </li>
          );
        })}
      </ul>
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
      <span className="inline-flex w-max items-center gap-1.5 rounded-full border border-border-muted bg-surface-secondary px-3 py-1 text-xs text-text-secondary">
        <Sparkles className="size-3.5 text-brand" aria-hidden />
        What is paper trading?
      </span>
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
