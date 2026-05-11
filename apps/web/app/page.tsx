import { ArrowRight } from "lucide-react";
import Link from "next/link";

import { TopMovers } from "@/components/top-movers";
import { Button } from "@/components/ui/button";

export default function HomePage() {
  return (
    <div className="container mx-auto px-6 py-16">
      <section className="mx-auto max-w-3xl text-center">
        <h1 className="text-5xl font-bold tracking-tight sm:text-6xl">
          Market Intelligence <span className="text-primary">Simplified</span>
        </h1>
        <p className="mt-6 text-lg text-muted-foreground">
          Live market data, technical indicators, and a paper-trading simulator. Built for investors
          who want to learn without risking real money.
        </p>
        <div className="mt-10 flex items-center justify-center gap-4">
          <Button asChild size="lg">
            <Link href="/markets" className="gap-2">
              Explore Markets
              <ArrowRight className="h-4 w-4" />
            </Link>
          </Button>
          <Button asChild size="lg" variant="outline">
            <Link href="/signup">Create account</Link>
          </Button>
        </div>
      </section>

      <section className="mx-auto mt-20 max-w-5xl">
        <div className="mb-4 flex items-baseline justify-between">
          <h2 className="text-lg font-semibold">Featured tickers</h2>
          <Link href="/markets" className="text-sm text-muted-foreground hover:text-foreground">
            See all →
          </Link>
        </div>
        <TopMovers />
      </section>
    </div>
  );
}
