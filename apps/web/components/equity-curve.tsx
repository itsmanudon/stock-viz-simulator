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

type Point = { date: string; nav: string };

function toUtcSeconds(yyyyMmDd: string): UTCTimestamp {
  // Treat as midnight UTC so the candle aligns with the labelled day.
  return Math.floor(new Date(`${yyyyMmDd}T00:00:00Z`).getTime() / 1000) as UTCTimestamp;
}

export function EquityCurve({ points }: { points: Point[] }) {
  const containerRef = useRef<HTMLDivElement | null>(null);

  const data = useMemo(
    () => points.map((p) => ({ time: toUtcSeconds(p.date), value: Number(p.nav) })),
    [points],
  );

  useEffect(() => {
    if (!containerRef.current) return;

    const chart: IChartApi = createChart(containerRef.current, {
      autoSize: true,
      layout: {
        background: { color: "transparent" },
        textColor: "rgb(161 161 170)",
      },
      grid: {
        vertLines: { color: "rgba(82, 82, 91, 0.3)" },
        horzLines: { color: "rgba(82, 82, 91, 0.3)" },
      },
      timeScale: { borderColor: "rgb(63 63 70)", timeVisible: false },
      rightPriceScale: { borderColor: "rgb(63 63 70)" },
      crosshair: { mode: 1 },
    });

    const series = chart.addSeries(AreaSeries, {
      lineColor: "rgb(34 197 94)",
      topColor: "rgba(34, 197, 94, 0.35)",
      bottomColor: "rgba(34, 197, 94, 0.02)",
      lineWidth: 2,
      priceLineVisible: false,
    });
    series.setData(data);
    chart.timeScale().fitContent();

    return () => {
      chart.remove();
    };
  }, [data]);

  return <div ref={containerRef} className="h-[260px] w-full" />;
}
