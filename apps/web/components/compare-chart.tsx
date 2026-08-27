"use client";

/**
 * Multi-ticker normalized line chart.
 *
 * Each series is rebased to 100 at the first bar in the window so the lines
 * are comparable regardless of absolute price level.
 */

import { type IChartApi, LineSeries, type UTCTimestamp, createChart } from "lightweight-charts";
import { useTheme } from "next-themes";
import { useEffect, useId, useRef } from "react";

import type { Bar } from "@/lib/api";
import { seriesColor } from "@/lib/compare-workspace";

type Series = { ticker: string; bars: Bar[]; color?: string };

function toUtcSeconds(iso: string): UTCTimestamp {
  return Math.floor(new Date(iso).getTime() / 1000) as UTCTimestamp;
}

export function CompareChart({
  series,
  accessibleLabel = "Normalized performance comparison chart, rebased to 100.",
}: {
  series: Series[];
  accessibleLabel?: string;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const { resolvedTheme } = useTheme();
  const summaryId = useId();

  const summaries = series.map((item) => {
    if (item.bars.length === 0) return { ticker: item.ticker, last: null as number | null };
    const base = Number(item.bars[0].close);
    const last = Number(item.bars[item.bars.length - 1].close);
    if (!base) return { ticker: item.ticker, last: null };
    return { ticker: item.ticker, last: (last / base) * 100 };
  });

  useEffect(() => {
    if (!containerRef.current) return;
    const isDark = resolvedTheme !== "light";
    const gridColor = isDark ? "rgba(133, 142, 158, 0.12)" : "rgba(84, 94, 110, 0.12)";
    const axisColor = isDark ? "rgba(133, 142, 158, 0.3)" : "rgba(84, 94, 110, 0.25)";
    const textColor = isDark ? "#9299a7" : "#657083";

    const chart: IChartApi = createChart(containerRef.current, {
      autoSize: true,
      layout: {
        background: { color: "transparent" },
        textColor,
      },
      grid: {
        vertLines: { color: gridColor },
        horzLines: { color: gridColor },
      },
      timeScale: { borderColor: axisColor },
      rightPriceScale: { borderColor: axisColor },
      crosshair: { mode: 1 },
      handleScale: true,
    });

    series.forEach((item, index) => {
      if (item.bars.length === 0) return;
      const base = Number(item.bars[0].close);
      if (base === 0) return;
      const points = item.bars.map((bar) => ({
        time: toUtcSeconds(bar.ts),
        value: (Number(bar.close) / base) * 100,
      }));
      const line = chart.addSeries(LineSeries, {
        color: item.color ?? seriesColor(index),
        lineWidth: 2,
        title: item.ticker,
        priceFormat: { type: "price", precision: 2, minMove: 0.01 },
        lastValueVisible: true,
      });
      line.setData(points);
    });

    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [resolvedTheme, series]);

  return (
    <div>
      <div role="img" aria-label={accessibleLabel} aria-describedby={summaryId}>
        <div
          ref={containerRef}
          aria-hidden="true"
          className="h-[320px] w-full sm:h-[420px] lg:h-[480px]"
        />
      </div>
      <p id={summaryId} className="sr-only">
        {summaries
          .map((item) =>
            item.last === null
              ? `${item.ticker} has no comparable history.`
              : `${item.ticker} ended the window at ${item.last.toFixed(2)} versus 100 at the start.`,
          )
          .join(" ")}
      </p>
      <ul className="mt-4 flex flex-wrap gap-x-4 gap-y-2 text-xs" aria-label="Series legend">
        {series.map((item, index) => (
          <li key={item.ticker} className="inline-flex items-center gap-2">
            <span
              className="size-2.5 rounded-full"
              style={{ backgroundColor: item.color ?? seriesColor(index) }}
              aria-hidden
            />
            <span className="font-mono">{item.ticker}</span>
            {item.bars.length === 0 ? <span className="text-text-tertiary">no history</span> : null}
          </li>
        ))}
      </ul>
    </div>
  );
}
