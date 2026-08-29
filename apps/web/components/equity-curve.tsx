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

import { useChartPalette } from "@/lib/chart-theme";

type Point = { date: string; nav: string };

function toUtcSeconds(yyyyMmDd: string): UTCTimestamp {
  // Treat as midnight UTC so the candle aligns with the labelled day.
  return Math.floor(new Date(`${yyyyMmDd}T00:00:00Z`).getTime() / 1000) as UTCTimestamp;
}

export function EquityCurve({
  points,
  accessibleLabel = "Portfolio USD NAV history chart.",
}: {
  points: Point[];
  accessibleLabel?: string;
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
    });

    const series = chart.addSeries(AreaSeries, {
      lineColor,
      topColor: fillColor,
      bottomColor: "rgba(0, 0, 0, 0)",
      lineWidth: 2,
      priceLineVisible: false,
    });
    series.setData(data);
    chart.timeScale().fitContent();

    return () => {
      chart.remove();
    };
  }, [data, isPositive, palette]);

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
