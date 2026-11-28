/**
 * Closing call to action.
 *
 * Full-bleed and neutral, with one soft brand glow behind the heading (an
 * Aurora brand moment) rather than a saturated brand block.
 *
 * The oversized hollow "$100,000" behind the heading is the ReadMe
 * oversized-wordmark trick applied to the number the copy is actually about.
 * It is decorative and `aria-hidden`; the figure is already in the heading.
 *
 * Behind both, the PRISM light leans green or red with the last session's
 * breadth, as ambient colour only.
 */

import { ArrowRight } from "lucide-react";
import Link from "next/link";

import { loadBreadth } from "@/components/marketing/proofs/breadth";
import { Reveal } from "@/components/marketing/reveal";
import { LiquidChrome } from "@/components/prism/liquid-chrome";
import { Magnetic } from "@/components/prism/magnetic";
import { Button } from "@/components/ui/button";
import { signupMode } from "@/lib/signup-gate";
import { ctaPair } from "@/lib/signup-policy";

export async function ClosingCta() {
  // The signup switch: while closed, the account button points at a public page.
  const [primary, secondary] = ctaPair(
    signupMode(),
    { href: "/signup", label: "Create free account" },
    { href: "/markets", label: "See the markets" },
  );
  const breadth = await loadBreadth();
  return (
    <section className="relative isolate overflow-hidden border-y border-border-muted bg-surface-secondary">
      <LiquidChrome share={breadth?.share ?? null} className="inset-0" />
      <span
        aria-hidden
        className="brand-glow top-1/2 left-1/2 -z-10 h-80 w-[48rem] -translate-x-1/2 -translate-y-1/2 opacity-70"
      />
      <span
        aria-hidden
        className="text-outline pointer-events-none absolute inset-x-0 top-1/2 -z-10 -translate-y-1/2 text-center font-mono text-[clamp(5rem,22vw,18rem)] leading-none font-bold whitespace-nowrap select-none [--outline-color:var(--background)] opacity-[0.7]"
      >
        $100,000
      </span>

      <div className="mx-auto w-full max-w-3xl px-4 py-20 text-center sm:px-6 sm:py-28">
        <Reveal>
          <h2 className="text-4xl font-medium tracking-[-0.045em] text-balance sm:text-6xl lg:text-7xl">
            Start with $100,000 that{" "}
            <span className="font-editorial text-prism pr-1">isn&rsquo;t</span> real
          </h2>
          <p className="mx-auto mt-4 max-w-xl text-base leading-7 text-text-secondary text-pretty">
            Make the expensive mistakes here instead. Your portfolio, orders, and alerts are saved
            to your account.
          </p>
          <div className="mt-9 flex flex-wrap items-center justify-center gap-3">
            <Magnetic>
              <Button asChild size="lg" className="prism-cta h-12 rounded-full px-7 text-base">
                <Link href={primary.href} className="gap-2">
                  {primary.label}
                  <ArrowRight className="size-4" aria-hidden />
                </Link>
              </Button>
            </Magnetic>
            <Button asChild size="lg" variant="outline" className="glass rounded-full px-6">
              <Link href={secondary.href}>{secondary.label}</Link>
            </Button>
          </div>
        </Reveal>
      </div>
    </section>
  );
}
