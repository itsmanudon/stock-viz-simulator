"use client";

/**
 * "Replay my trade" (A6.10, M9.5): a read-only playback of a journal entry.
 * The bars appear one at a time (1, 2, 5 or 10 a second, the Replay Lab's
 * speeds), with the user's real fills marked as they happened and the plan's
 * lines drawn. Running MAE and MFE grow with each bar while shares are held.
 * No orders: nothing here calls the API.
 */

import { useEffect, useMemo, useState } from "react";

import { PriceChart, type PriceChartLine } from "@/components/price-chart";
import { Button } from "@/components/ui/button";
import type { Bar } from "@/lib/api";
import type { TradeReplay } from "@/lib/api/journal-entries";
import type { ChartEvent } from "@/lib/chart-events";
import { useChartPalette } from "@/lib/chart-theme";
import { formatCurrency } from "@/lib/portfolio-view-model";
import { AUTOPLAY_SPEEDS, type AutoplaySpeed } from "@/lib/replay";

/** The bar index a fill belongs to (its minute, or its day on daily bars). */
export function fillBarIndex(bars: TradeReplay["bars"], at: string, interval: string): number {
  const t = Date.parse(at.endsWith("Z") ? at : `${at}Z`);
  for (let i = bars.length - 1; i >= 0; i--) {
    const ts = Date.parse(bars[i].ts.endsWith("Z") ? bars[i].ts : `${bars[i].ts}Z`);
    if (interval === "1m" ? ts <= t : bars[i].ts.slice(0, 10) <= at.slice(0, 10)) return i;
  }
  return 0;
}

/** Running MAE and MFE per share up to bar `upto` (inclusive), from the average cost. */
export function runningExcursions(
  replay: TradeReplay,
  upto: number,
): { mae: number | null; mfe: number | null } {
  const short = replay.side === "short";
  const opening = short ? "sell" : "buy";
  let qty = 0;
  let avg = 0;
  let mae: number | null = null;
  let mfe: number | null = null;
  const fillsAt = replay.fills.map((f) => fillBarIndex(replay.bars, f.at, replay.interval));
  for (let i = 0; i <= upto && i < replay.bars.length; i++) {
    const bar = replay.bars[i];
    if (qty > 0) {
      const low = Number(bar.low);
      const high = Number(bar.high);
      const adverse = short ? avg - high : low - avg;
      const favourable = short ? avg - low : high - avg;
      mae = mae === null ? adverse : Math.min(mae, adverse);
      mfe = mfe === null ? favourable : Math.max(mfe, favourable);
    }
    replay.fills.forEach((f, k) => {
      if (fillsAt[k] !== i) return;
      const q = Number(f.quantity);
      const p = Number(f.price);
      if (f.side === opening) {
        avg = (avg * qty + p * q) / (qty + q);
        qty += q;
      } else {
        qty -= q;
      }
    });
  }
  return { mae, mfe };
}

export function TradeReplayPlayer({ replay }: { replay: TradeReplay }) {
  const palette = useChartPalette();
  const total = replay.bars.length;
  const firstFill = replay.fills.length
    ? fillBarIndex(replay.bars, replay.fills[0].at, replay.interval)
    : 0;
  // Start a few bars before the entry so the approach is visible.
  const [index, setIndex] = useState(() => Math.max(0, Math.min(firstFill - 1, total - 1)));
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState<AutoplaySpeed>(1);
  const atEnd = index >= total - 1;

  useEffect(() => {
    if (!playing || atEnd) return;
    const id = window.setTimeout(() => setIndex((i) => Math.min(i + 1, total - 1)), 1000 / speed);
    return () => window.clearTimeout(id);
  }, [playing, atEnd, speed, total]);

  useEffect(() => {
    if (atEnd) setPlaying(false);
  }, [atEnd]);

  const shown = useMemo<Bar[]>(() => replay.bars.slice(0, index + 1), [replay.bars, index]);
  const events = useMemo<ChartEvent[]>(() => {
    const lastTs = replay.bars[index]?.ts ?? "";
    return replay.fills
      .filter((f) => fillBarIndex(replay.bars, f.at, replay.interval) <= index && lastTs)
      .map((f) => ({
        type: "fill" as const,
        date: f.at.slice(0, 10),
        ts: f.at,
        side: f.side,
        quantity: f.quantity,
        price: f.price,
        r_multiple: null,
        book_id: null,
        journal_entry_id: replay.entry_id,
        closes_entry: false,
      }));
  }, [replay, index]);
  const lines = useMemo<PriceChartLine[]>(() => {
    const out: PriceChartLine[] = [];
    if (replay.planned_entry) {
      out.push({
        price: Number(replay.planned_entry),
        title: "Plan entry",
        color: palette.drawing.foreground,
        dashed: true,
      });
    }
    if (replay.planned_stop) {
      out.push({ price: Number(replay.planned_stop), title: "Stop", color: palette.negative });
    }
    if (replay.planned_target) {
      out.push({ price: Number(replay.planned_target), title: "Target", color: palette.positive });
    }
    return out;
  }, [replay, palette]);
  const running = useMemo(() => runningExcursions(replay, index), [replay, index]);
  const money = (value: number | null) =>
    value === null ? "—" : formatCurrency(value.toFixed(2), replay.currency);

  if (total === 0) {
    return (
      <p className="rounded-md border border-dashed border-border-muted px-4 py-6 text-sm text-text-secondary">
        No stored bars for this entry, so there is nothing to play back.
      </p>
    );
  }
  return (
    <div className="space-y-4" data-testid="trade-replay">
      <div className="flex flex-wrap items-center gap-2">
        <Button
          type="button"
          size="sm"
          onClick={() => (atEnd ? setIndex(0) : setPlaying((p) => !p))}
          data-testid="trade-replay-play"
        >
          {atEnd ? "Restart" : playing ? "Pause" : "Play"}
        </Button>
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={atEnd}
          onClick={() => setIndex((i) => Math.min(i + 1, total - 1))}
          data-testid="trade-replay-step"
        >
          Next bar
        </Button>
        <fieldset className="flex items-center gap-1 border-0 p-0" aria-label="Speed">
          {AUTOPLAY_SPEEDS.map((s) => (
            <Button
              key={s}
              type="button"
              size="sm"
              variant={s === speed ? "secondary" : "ghost"}
              aria-pressed={s === speed}
              onClick={() => setSpeed(s)}
            >
              {s}×
            </Button>
          ))}
        </fieldset>
        <p className="text-xs text-text-tertiary" data-testid="trade-replay-position">
          Bar {index + 1} of {total} · {replay.bars_note}
        </p>
      </div>
      <PriceChart
        bars={shown}
        events={events}
        priceLines={lines}
        currency={replay.currency}
        interval={replay.interval}
        showVolume={false}
      />
      <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
        <div>
          <dt className="text-xs text-text-tertiary">MAE so far (per share)</dt>
          <dd className="font-mono tabular-nums text-negative" data-testid="trade-replay-mae">
            {money(running.mae)}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-text-tertiary">MFE so far (per share)</dt>
          <dd className="font-mono tabular-nums text-positive" data-testid="trade-replay-mfe">
            {money(running.mfe)}
          </dd>
        </div>
      </dl>
    </div>
  );
}
