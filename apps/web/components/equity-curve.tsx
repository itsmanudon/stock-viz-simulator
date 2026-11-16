"use client";

/**
 * Equity-curve area chart for the portfolio page.
 *
 * Client component — lightweight-charts touches ``window`` on init. Reuses
 * the same library and styling conventions as ``price-chart.tsx`` but with a
 * single AreaSeries since we only ever plot NAV over time.
 */

import { AreaSeries, type IChartApi, type UTCTimestamp, createChart } from "lightweight-charts";
import { useEffect, useMemo, useRef } from "react";

import { fitWithLabelRoom } from "@/lib/chart-range";
import { useChartPalette } from "@/lib/chart-theme";

type Point = { date: string; nav: string };

function toUtcSeconds(yyyyMmDd: string): UTCTimestamp {
  // Treat as midnight UTC so the candle aligns with the labelled day.
  return Math.floor(new Date(`${yyyyMmDd}T00:00:00Z`).getTime() / 1000) as UTCTimestamp;
}

/** Whole units with grouping, in the series' currency (UX-9). */
export function axisFormatter(currency: string): (value: number) => string {
  let format: Intl.NumberFormat;
  try {
    format = new Intl.NumberFormat("en-US", {
      style: "currency",
      currency,
      maximumFractionDigits: 0,
    });
  } catch {
    format = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });
  }
  return (value: number) => format.format(value);
}

export function EquityCurve({
  points,
  accessibleLabel = "Portfolio NAV history chart.",
  currency = "USD",
}: {
  points: Point[];
  accessibleLabel?: string;
  /** UX-9 (Phase 8.6): the price axis prints this currency with grouping. */
  currency?: string;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const palette = useChartPalette();

  const data = useMemo(
    () => points.map((p) => ({ time: toUtcSeconds(p.date), value: Number(p.nav) })),
    [points],
  );
  const isPositive = data.length < 2 || data[data.length - 1].value >= data[0].value;

  useEffect(() => {
    if (!containerRef.current) return;

    const lineColor = isPositive ? palette.positive : palette.negative;
    const fillColor = isPositive ? palette.positiveFill : palette.negativeFill;

    const chart: IChartApi = createChart(containerRef.current, {
      autoSize: true,
      layout: {
        background: { color: "transparent" },
        textColor: palette.text,
      },
      grid: {
        vertLines: { color: palette.grid },
        horzLines: { color: palette.grid },
      },
      timeScale: { borderColor: palette.axis, timeVisible: false },
      rightPriceScale: { borderColor: palette.axis },
      crosshair: { mode: 1 },
      // UX-9: "$106,000", not "106000.00".
      localization: { priceFormatter: axisFormatter(currency) },
    });

    const series = chart.addSeries(AreaSeries, {
      lineColor,
      topColor: fillColor,
      bottomColor: "rgba(0, 0, 0, 0)",
      lineWidth: 2,
      priceLineVisible: false,
    });
    series.setData(data);
    fitWithLabelRoom(chart, data.length, (containerRef.current?.clientWidth ?? 0) - 64);

    return () => {
      chart.remove();
    };
  }, [data, isPositive, palette, currency]);

  return (
    <div role="img" aria-label={accessibleLabel} className="w-full">
      <div
        ref={containerRef}
        aria-hidden="true"
        className="h-[240px] w-full sm:h-[300px] lg:h-[340px]"
      />
    </div>
  );
}
