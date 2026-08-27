"use client";

/**
 * Equity-curve area chart for the portfolio page.
 *
 * Client component — lightweight-charts touches ``window`` on init. Reuses
 * the same library and styling conventions as ``price-chart.tsx`` but with a
 * single AreaSeries since we only ever plot NAV over time.
 */

import { AreaSeries, type IChartApi, type UTCTimestamp, createChart } from "lightweight-charts";
import { useTheme } from "next-themes";
import { useEffect, useMemo, useRef } from "react";

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
  const { resolvedTheme } = useTheme();

  const data = useMemo(
    () => points.map((p) => ({ time: toUtcSeconds(p.date), value: Number(p.nav) })),
    [points],
  );
  const isPositive = data.length < 2 || data[data.length - 1].value >= data[0].value;

  useEffect(() => {
    if (!containerRef.current) return;

    const isDark = resolvedTheme !== "light";
    const lineColor = isPositive
      ? isDark
        ? "#2ba477"
        : "#187c59"
      : isDark
        ? "#d75d63"
        : "#b83f48";
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
      timeScale: { borderColor: axisColor, timeVisible: false },
      rightPriceScale: { borderColor: axisColor },
      crosshair: { mode: 1 },
    });

    const series = chart.addSeries(AreaSeries, {
      lineColor,
      topColor: isPositive
        ? isDark
          ? "rgba(43, 164, 119, 0.28)"
          : "rgba(24, 124, 89, 0.2)"
        : isDark
          ? "rgba(215, 93, 99, 0.24)"
          : "rgba(184, 63, 72, 0.18)",
      bottomColor: "rgba(0, 0, 0, 0)",
      lineWidth: 2,
      priceLineVisible: false,
    });
    series.setData(data);
    chart.timeScale().fitContent();

    return () => {
      chart.remove();
    };
  }, [data, isPositive, resolvedTheme]);

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
