/**
 * /pairs — A9.3 (M7.6): the pairs lab. Two stored symbols, an Engle-Granger
 * test (OLS hedge ratio, ADF on the residual against MacKinnon's critical
 * values), the half-life of the spread, its z-score and the rolling hedge
 * ratio. URL state: `a`, `b`, `years`. Says plainly when the test does not
 * reject.
 */

import type { Metadata } from "next";

import { PageHeader } from "@/components/page-header";
import { Sparkline } from "@/components/sparkline";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { type Pair, getPair } from "@/lib/api/research-views";

export const metadata: Metadata = { title: "Pairs lab" };

type Search = { a?: string; b?: string; years?: string };

export default async function PairsPage({ searchParams }: { searchParams: Promise<Search> }) {
  const raw = await searchParams;
  const a = (raw.a ?? "").trim().toUpperCase().slice(0, 16);
  const b = (raw.b ?? "").trim().toUpperCase().slice(0, 16);
  const years = Math.min(15, Math.max(1, Number(raw.years) || 3));
  let pair: Pair | null = null;
  let error: string | null = null;
  if (a && b) {
    try {
      pair = await getPair(a, b, years);
    } catch (err) {
      error =
        err instanceof Error && /404/.test(err.message)
          ? "One of those symbols is not stored."
          : "The test could not run.";
    }
  }
  return (
    <div className="w-full space-y-6 px-4 py-6 sm:px-6 lg:py-7 xl:px-8">
      <PageHeader
        eyebrow="Quant Lab"
        title="Pairs lab"
        description="Do two stocks share a long-run relationship? An Engle-Granger cointegration test on their stored closes."
      />
      <form method="get" className="flex flex-wrap items-end gap-2" data-testid="pairs-form">
        {(
          [
            ["a", "First symbol", a],
            ["b", "Second symbol", b],
          ] as const
        ).map(([name, label, value]) => (
          <div key={name} className="space-y-1">
            <Label htmlFor={`pair-${name}`} className="text-xs">
              {label}
            </Label>
            <Input
              id={`pair-${name}`}
              name={name}
              defaultValue={value}
              placeholder="KO"
              className="w-32"
            />
          </div>
        ))}
        <div className="space-y-1">
          <Label htmlFor="pair-years" className="text-xs">
            Years
          </Label>
          <Input id="pair-years" name="years" defaultValue={String(years)} className="w-20" />
        </div>
        <Button type="submit">Test</Button>
      </form>
      {error ? <p className="text-sm text-negative">{error}</p> : null}
      {pair ? (
        pair.reason ? (
          <p className="text-sm text-text-secondary">{pair.reason}</p>
        ) : (
          <section className="space-y-4" data-testid="pair-result">
            <p className="text-sm" data-testid="pair-verdict">
              {pair.cointegrated_at
                ? `Cointegrated at the ${pair.cointegrated_at} level over ${pair.sessions} common sessions (${pair.first} to ${pair.last}).`
                : `No evidence of cointegration over ${pair.sessions} common sessions: the test does not reject at 10%.`}
            </p>
            <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              {(
                [
                  ["Hedge ratio (β)", pair.beta?.toFixed(3)],
                  ["ADF τ", pair.tau?.toFixed(2)],
                  ["5% critical value", pair.critical["5%"]?.toFixed(2)],
                  ["Half-life (sessions)", pair.half_life?.toFixed(1) ?? "no pull back"],
                  ["Spread z-score now", pair.zscore?.toFixed(2)],
                ] as const
              ).map(([label, value]) => (
                <div key={label}>
                  <dt className="text-xs text-text-tertiary">{label}</dt>
                  <dd className="font-mono text-sm tabular-nums">{value ?? "—"}</dd>
                </div>
              ))}
            </dl>
            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <p className="text-xs text-text-tertiary">
                  Spread: ln {pair.a} − β ln {pair.b}
                </p>
                <Sparkline closes={pair.spread.map((p) => p.spread ?? 0)} width={320} height={60} />
              </div>
              <div>
                <p className="text-xs text-text-tertiary">Rolling 60-session hedge ratio</p>
                <Sparkline
                  closes={pair.rolling_beta.map((p) => p.beta ?? 0)}
                  width={320}
                  height={60}
                />
              </div>
            </div>
            <p className="text-xs text-text-tertiary">{pair.method}</p>
          </section>
        )
      ) : null}
    </div>
  );
}
