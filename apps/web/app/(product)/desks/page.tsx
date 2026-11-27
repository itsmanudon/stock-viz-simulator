/**
 * /desks — A7.13: four desk presets (Swing, Compounder, Derivatives, Quant).
 * Each lists its tools, a starting screen and a chart look; `?desk=&ticker=`
 * opens the stock page with that look (a redirect, so the link is shareable).
 */

import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";

import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { DESKS, deskById, deskChartHref, deskScreenHref } from "@/lib/desks";

export const metadata: Metadata = { title: "Desks" };

export default async function DesksPage({
  searchParams,
}: {
  searchParams: Promise<{ desk?: string; ticker?: string }>;
}) {
  const raw = await searchParams;
  const desk = deskById(raw.desk);
  const ticker = (raw.ticker ?? "").trim().slice(0, 16);
  if (desk && ticker) redirect(deskChartHref(desk, ticker));
  return (
    <div className="w-full space-y-6 px-4 py-6 sm:px-6 lg:py-7 xl:px-8">
      <PageHeader
        title="Desks"
        description="Four ways in: the tools each trading style opens with, a screen to start from and a chart look."
      />
      <ul className="grid gap-4 md:grid-cols-2" data-testid="desks">
        {DESKS.map((d) => (
          <li
            key={d.id}
            className="space-y-3 rounded-xl border border-border bg-card p-4"
            data-testid="desk"
            data-desk={d.id}
          >
            <div>
              <h2 className="text-base font-semibold">{d.name}</h2>
              <p className="text-sm text-text-secondary">{d.summary}</p>
            </div>
            <ul className="flex flex-wrap gap-2 text-xs">
              {d.tools.map((t) => (
                <li key={t.href}>
                  <Link
                    href={t.href}
                    className="inline-flex rounded-full border border-border px-2.5 py-1 hover:bg-muted"
                  >
                    {t.label}
                  </Link>
                </li>
              ))}
            </ul>
            <p className="text-xs">
              <Link href={deskScreenHref(d)} className="underline" data-testid="desk-screen">
                Start from the {d.name.replace(" Desk", "").toLowerCase()} screen
              </Link>
            </p>
            <form method="get" className="flex items-end gap-2">
              <input type="hidden" name="desk" value={d.id} />
              <label className="sr-only" htmlFor={`desk-ticker-${d.id}`}>
                Symbol for the {d.name}
              </label>
              <Input
                id={`desk-ticker-${d.id}`}
                name="ticker"
                placeholder="Symbol, e.g. TCS.NS"
                className="w-44"
              />
              <Button type="submit" variant="outline">
                Open Chart
              </Button>
            </form>
            <p className="text-2xs text-text-tertiary">
              Chart look: {d.chart.indicators.join(", ")}
              {d.chart.type ? `, ${d.chart.type} chart` : ""}
              {d.chart.tab ? `, opens on ${d.chart.tab}` : ""}.
            </p>
          </li>
        ))}
      </ul>
    </div>
  );
}
