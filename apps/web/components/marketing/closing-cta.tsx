/**
 * Closing call to action.
 *
 * Full-bleed and gold-tinted — the one place on the page where the brand
 * colour fills a large area, which is what makes it read as the end of the
 * argument rather than another section.
 *
 * The oversized hollow "$100,000" behind the heading is the ReadMe
 * oversized-wordmark trick applied to the number the copy is actually about.
 * It is decorative and `aria-hidden`; the figure is already in the heading.
 */

import { ArrowRight } from "lucide-react";
import Link from "next/link";

import { Reveal } from "@/components/marketing/reveal";
import { Button } from "@/components/ui/button";

export function ClosingCta() {
  return (
    <section className="relative isolate overflow-hidden border-y border-border-muted bg-brand-muted">
      <span
        aria-hidden
        className="text-outline pointer-events-none absolute inset-x-0 top-1/2 -z-10 -translate-y-1/2 text-center font-mono text-[clamp(5rem,22vw,18rem)] leading-none font-bold whitespace-nowrap select-none [--outline-color:var(--brand)]"
      >
        $100,000
      </span>

      <div className="mx-auto w-full max-w-3xl px-4 py-20 text-center sm:px-6 sm:py-28">
        <Reveal>
          <h2 className="text-3xl font-semibold tracking-tight text-balance sm:text-4xl lg:text-5xl">
            Start with $100,000 that isn&rsquo;t real
          </h2>
          <p className="mx-auto mt-4 max-w-xl text-base leading-7 text-text-secondary text-pretty">
            Make the expensive mistakes here instead. Your portfolio, orders, and alerts are saved
            to your account.
          </p>
          <div className="mt-9 flex flex-wrap items-center justify-center gap-3">
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
        </Reveal>
      </div>
    </section>
  );
}
