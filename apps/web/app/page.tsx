import { getApiHealth } from "@/lib/api";
import { ArrowRight } from "lucide-react";
import Link from "next/link";

export default async function HomePage() {
  const health = await getApiHealth();

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
          <Link
            href="/markets"
            className="inline-flex items-center gap-2 rounded-md bg-primary px-6 py-3 text-sm font-medium text-primary-foreground transition hover:opacity-90"
          >
            Explore Markets
            <ArrowRight className="h-4 w-4" />
          </Link>
        </div>
      </section>

      <section className="mx-auto mt-24 max-w-2xl">
        <div className="rounded-lg border bg-card p-6">
          <h2 className="text-sm font-medium text-muted-foreground">Backend status</h2>
          <div className="mt-2 flex items-center gap-3">
            <span
              className={`inline-block h-2 w-2 rounded-full ${
                health.status === "ok" ? "bg-green-500" : "bg-amber-500"
              }`}
              aria-hidden
            />
            <span className="font-mono text-sm">
              {health.status} · api v{health.version} · db {health.database}
            </span>
          </div>
        </div>
      </section>
    </div>
  );
}
