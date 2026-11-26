"use client";

/**
 * The journal entry's chart (A5.5): A3's `PriceChart` with the entry's fills
 * as fill markers (the closing fill carries the entry's R, as on the stock
 * page), the plan's entry, stop and target as labelled lines, and MAE / MFE
 * marked on the bars where they happened.
 */

import { useMemo } from "react";

import { PriceChart, type PriceChartLine, type PriceChartMarker } from "@/components/price-chart";
import type { Bar } from "@/lib/api";
import type { ChartEvent } from "@/lib/chart-events";
import { useChartPalette } from "@/lib/chart-theme";
import { type JournalEntry, excursionPct } from "@/lib/journal-entries";

export function JournalEntryChart({ entry, bars }: { entry: JournalEntry; bars: Bar[] }) {
  const palette = useChartPalette();
  const closing = entry.status === "closed" ? entry.fills.length - 1 : -1;
  const events = useMemo<ChartEvent[]>(
    () =>
      entry.fills.map((f, i) => ({
        type: "fill" as const,
        date: f.venue_date,
        ts: f.at,
        side: f.side,
        quantity: f.quantity,
        price: f.price,
        r_multiple: i === closing ? (entry.r_multiple ?? null) : null,
        book_id: entry.book_id ?? null,
        journal_entry_id: entry.id,
        closes_entry: i === closing,
      })),
    [entry, closing],
  );
  const markers = useMemo<PriceChartMarker[]>(() => {
    const out: PriceChartMarker[] = [];
    const { mae, mfe } = entry.excursions;
    if (mae) {
      out.push({
        time: `${mae.date}T00:00:00`,
        position: "belowBar",
        color: palette.negative,
        shape: "circle",
        text: `MAE ${excursionPct(mae)}`,
      });
    }
    if (mfe) {
      out.push({
        time: `${mfe.date}T00:00:00`,
        position: "aboveBar",
        color: palette.positive,
        shape: "circle",
        text: `MFE ${excursionPct(mfe)}`,
      });
    }
    return out;
  }, [entry.excursions, palette]);
  const lines = useMemo<PriceChartLine[]>(() => {
    const plan = entry.plan;
    if (!plan) return [];
    const out: PriceChartLine[] = [];
    if (plan.planned_entry) {
      out.push({
        price: Number(plan.planned_entry),
        title: "Plan entry",
        color: palette.drawing.foreground,
        dashed: true,
      });
    }
    if (plan.planned_stop) {
      out.push({ price: Number(plan.planned_stop), title: "Stop", color: palette.negative });
    }
    if (plan.planned_target) {
      out.push({ price: Number(plan.planned_target), title: "Target", color: palette.positive });
    }
    return out;
  }, [entry.plan, palette]);

  if (bars.length === 0) {
    return (
      <p className="rounded-md border border-dashed border-border-muted px-4 py-6 text-sm text-text-secondary">
        No stored bars for these dates, so there is no chart.
      </p>
    );
  }
  return (
    <div data-testid="journal-entry-chart">
      <PriceChart
        bars={bars}
        events={events}
        markers={markers}
        priceLines={lines}
        currency={entry.currency}
        showVolume={false}
      />
    </div>
  );
}
