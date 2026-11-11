/**
 * Marketing hero, in the Aurora direction (SolCard's composition).
 *
 * Centred: a glass badge, the headline, two pill buttons and the honest
 * constraints as chips. Below them the product sits on a stage over a wide
 * brand glow: the real-data product panel, the paper account card tucked
 * against it, and glass pills naming facts about the simulator.
 *
 * The constraints (end-of-day data, simulated fills) stay in the chips as
 * text; the stage is a picture and is hidden from assistive technology, so
 * nothing on it may be the only place a fact appears.
 */

import { ArrowRight, CalendarCheck, Check, Database, ShieldCheck, Wallet } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import Link from "next/link";

import { HeroPanel } from "@/components/marketing/hero-panel";
import { PaperCard } from "@/components/paper-card";
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

/** Floating facts around the panel, from `lg` up. Each is true of the product. */
const STAGE_PILLS: { icon: LucideIcon; label: string; className: string }[] = [
  {
    icon: Wallet,
    label: "$100,000 paper balance",
    className: "top-28 -left-10 xl:-left-24",
  },
  {
    icon: CalendarCheck,
    label: "Every close dated",
    className: "top-24 -right-10 xl:-right-28",
  },
  {
    icon: ShieldCheck,
    label: "Fills at stored daily closes",
    className: "top-48 -right-6 xl:-right-16",
  },
];

export async function Hero() {
  const count = await symbolCount();

  const chips: { icon: LucideIcon; label: string }[] = [
    { icon: Check, label: "No card required" },
    ...(count ? [{ icon: Database, label: `${count} symbols tracked` }] : []),
    { icon: ShieldCheck, label: "Simulated fills · EOD data" },
  ];

  return (
    // `overflow-hidden` clips the glow and the floating pills, which are wider
    // than a phone on purpose; the marketing spec checks 320-1440 px.
    <section className="relative isolate overflow-hidden">
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
          Screen it, backtest it, then trade it on paper — and keep score of what your decisions
          were actually worth.
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

      <div className="relative mx-auto mt-14 w-full max-w-4xl px-4 pb-16 sm:mt-16 sm:px-6 sm:pb-24">
        <div
          aria-hidden
          className="brand-glow top-0 left-1/2 -z-10 h-[34rem] w-[64rem] -translate-x-1/2"
        />

        <div aria-hidden className="hidden lg:block">
          {STAGE_PILLS.map((pill) => {
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
          })}
        </div>

        <div className="relative">
          <HeroPanel />
          <PaperCard
            currency="USD"
            className="absolute -bottom-10 -left-8 z-10 hidden w-60 -rotate-6 md:flex xl:-left-20"
          />
        </div>
      </div>
    </section>
  );
}
