/**
 * Marketing hero.
 *
 * Asymmetric: copy left, the product panel right. The old hero was centered
 * text and two buttons, which never showed the thing being sold.
 *
 * The fine print moved into "proof chips" under the CTAs. That is deliberate —
 * the constraints (end-of-day data, simulated fills) are the honest shape of
 * the product, and every current benchmark in the category treats disclosure
 * as a design element instead of grey apology text at the bottom.
 */

import { ArrowRight, Check, Database, ShieldCheck } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import Link from "next/link";

import { HeroPanel } from "@/components/marketing/hero-panel";
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

export async function Hero() {
  const count = await symbolCount();

  const chips: { icon: LucideIcon; label: string }[] = [
    { icon: Check, label: "No card required" },
    ...(count ? [{ icon: Database, label: `${count} symbols tracked` }] : []),
    { icon: ShieldCheck, label: "Simulated fills · EOD data" },
  ];

  return (
    // `overflow-hidden` is load-bearing, not decorative: the panel below is
    // pulled past the right edge with a negative margin, and without a clipping
    // ancestor that widens the whole document and gives every laptop-width
    // viewport (1024-1400) a horizontal scrollbar.
    <section className="mx-auto w-full max-w-7xl overflow-hidden px-4 pt-12 pb-14 sm:px-6 sm:pt-20 lg:pt-24">
      <div className="grid items-center gap-12 lg:grid-cols-[minmax(0,1fr)_1.15fr] lg:gap-16">
        <div>
          <Link
            href="/trade"
            className="inline-flex items-center gap-2 rounded-full border border-brand/40 bg-brand/5 py-1 pr-2.5 pl-3 font-mono text-2xs tracking-[0.12em] text-brand uppercase transition-colors hover:bg-brand/10"
          >
            Options settlement
            <ArrowRight className="size-3" aria-hidden />
          </Link>

          <h1 className="mt-5 text-4xl font-semibold tracking-tight text-balance sm:text-5xl lg:text-6xl">
            Learn the market <span className="text-text-secondary">without risking the money</span>
          </h1>

          <p className="mt-6 max-w-xl text-lg leading-8 text-text-secondary text-pretty">
            Screen it, backtest it, then trade it on paper — and keep score of what your decisions
            were actually worth.
          </p>

          <div className="mt-9 flex flex-wrap items-center gap-3">
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

          <ul className="mt-8 flex flex-wrap items-center gap-x-5 gap-y-2.5">
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

        {/* Crops past the right edge on wide screens so the panel reads as a
            window onto a larger workspace rather than a framed screenshot. */}
        <div className="lg:-mr-12 xl:-mr-24">
          <HeroPanel />
        </div>
      </div>
    </section>
  );
}
