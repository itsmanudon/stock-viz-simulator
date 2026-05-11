"use client";

/**
 * Multi-ticker normalized line chart.
 *
 * Each series is rebased to 100 at the first bar in the window so the lines
 * are comparable regardless of absolute price level. Built on
 * lightweight-charts the same way PriceChart is.
 */

import { type IChartApi, LineSeries, type UTCTimestamp, createChart } from "lightweight-charts";
import { useEffect, useRef } from "react";

import type { Bar } from "@/lib/api";

const PALETTE = [
  "#3b82f6", // blue-500
  "#a855f7", // purple-500
  "#f59e0b", // amber-500
  "#22c55e", // green-500
  "#ec4899", // pink-500
  "#06b6d4", // cyan-500
];

type Props = {
  series: Array<{ ticker: string; bars: Bar[] }>;
};

function toUtcSeconds(iso: string): UTCTimestamp {
  return Math.floor(new Date(iso).getTime() / 1000) as UTCTimestamp;
}

export function CompareChart({ series }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);

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
      timeScale: { borderColor: "rgb(63 63 70)" },
      rightPriceScale: { borderColor: "rgb(63 63 70)" },
      crosshair: { mode: 1 },
    });

    series.forEach(({ ticker, bars }, idx) => {
      if (bars.length === 0) return;
      const base = Number(bars[0].close);
      if (base === 0) return;
      const points = bars.map((b) => ({
        time: toUtcSeconds(b.ts),
        value: (Number(b.close) / base) * 100,
      }));
      const line = chart.addSeries(LineSeries, {
        color: PALETTE[idx % PALETTE.length],
        lineWidth: 2,
        title: ticker,
        priceFormat: { type: "price", precision: 2, minMove: 0.01 },
      });
      line.setData(points);
    });

    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [series]);

  return <div ref={containerRef} className="h-[480px] w-full" />;
}
