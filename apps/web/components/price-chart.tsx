"use client";

/**
 * Candlestick + volume chart wrapping lightweight-charts.
 *
 * Client component: lightweight-charts touches ``window`` on init. We mount
 * once and recreate the chart only when the data identity changes. Indicator
 * overlay lines are added on top of the candlestick pane; MACD lives in its
 * own pane below the volume.
 */

import {
  CandlestickSeries,
  HistogramSeries,
  type IChartApi,
  LineSeries,
  type Time,
  type UTCTimestamp,
  createChart,
} from "lightweight-charts";
import { useEffect, useMemo, useRef } from "react";

import type { Bar, IndicatorPoint, MACDPoint } from "@/lib/api";

type Props = {
  bars: Bar[];
  overlays?: Record<string, IndicatorPoint[]>;
  macd?: MACDPoint[] | null;
};

function toUtcSeconds(iso: string): UTCTimestamp {
  return Math.floor(new Date(iso).getTime() / 1000) as UTCTimestamp;
}

const OVERLAY_COLORS = [
  "#3b82f6", // blue-500
  "#a855f7", // purple-500
  "#f59e0b", // amber-500
  "#ec4899", // pink-500
  "#22d3ee", // cyan-400
];

export function PriceChart({ bars, overlays, macd }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const macdRef = useRef<HTMLDivElement | null>(null);

  // Stable identity so the effect doesn't re-run on every render.
  const candles = useMemo(
    () =>
      bars.map((b) => ({
        time: toUtcSeconds(b.ts),
        open: Number(b.open),
        high: Number(b.high),
        low: Number(b.low),
        close: Number(b.close),
      })),
    [bars],
  );
  const volumes = useMemo(
    () =>
      bars.map((b) => ({
        time: toUtcSeconds(b.ts),
        value: b.volume,
        color: Number(b.close) >= Number(b.open) ? "rgba(34,197,94,0.4)" : "rgba(239,68,68,0.4)",
      })),
    [bars],
  );

  useEffect(() => {
    if (!containerRef.current) return;

    const chart: IChartApi = createChart(containerRef.current, {
      autoSize: true,
      layout: {
        background: { color: "transparent" },
        textColor: "rgb(161 161 170)", // zinc-400
      },
      grid: {
        vertLines: { color: "rgba(82, 82, 91, 0.3)" }, // zinc-600 @ 30%
        horzLines: { color: "rgba(82, 82, 91, 0.3)" },
      },
      timeScale: { borderColor: "rgb(63 63 70)", timeVisible: false },
      rightPriceScale: { borderColor: "rgb(63 63 70)" },
      crosshair: { mode: 1 },
    });

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: "rgb(34 197 94)",
      downColor: "rgb(239 68 68)",
      borderVisible: false,
      wickUpColor: "rgb(34 197 94)",
      wickDownColor: "rgb(239 68 68)",
    });
    candleSeries.setData(candles);

    const volumeSeries = chart.addSeries(HistogramSeries, {
      priceFormat: { type: "volume" },
      priceScaleId: "volume",
    });
    volumeSeries.setData(volumes);
    chart.priceScale("volume").applyOptions({
      scaleMargins: { top: 0.8, bottom: 0 },
    });

    // Overlay indicator lines on the price pane.
    let colorIdx = 0;
    for (const [name, points] of Object.entries(overlays ?? {})) {
      if (!points.length) continue;
      const line = chart.addSeries(LineSeries, {
        color: OVERLAY_COLORS[colorIdx % OVERLAY_COLORS.length],
        lineWidth: 2,
        priceLineVisible: false,
        title: name.toUpperCase(),
      });
      line.setData(points.map((p) => ({ time: toUtcSeconds(p.ts), value: p.value })));
      colorIdx += 1;
    }

    let macdChart: IChartApi | null = null;
    if (macd?.length && macdRef.current) {
      macdChart = createChart(macdRef.current, {
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
      });
      const macdLine = macdChart.addSeries(LineSeries, {
        color: "#3b82f6",
        lineWidth: 2,
        priceLineVisible: false,
        title: "MACD",
      });
      const signalLine = macdChart.addSeries(LineSeries, {
        color: "#f59e0b",
        lineWidth: 2,
        priceLineVisible: false,
        title: "Signal",
      });
      const histo = macdChart.addSeries(HistogramSeries, {
        priceLineVisible: false,
      });
      macdLine.setData(macd.map((p) => ({ time: toUtcSeconds(p.ts), value: p.macd })));
      signalLine.setData(macd.map((p) => ({ time: toUtcSeconds(p.ts), value: p.signal })));
      histo.setData(
        macd.map((p) => ({
          time: toUtcSeconds(p.ts) as Time,
          value: p.histogram,
          color: p.histogram >= 0 ? "rgba(34,197,94,0.5)" : "rgba(239,68,68,0.5)",
        })),
      );
    }

    chart.timeScale().fitContent();
    macdChart?.timeScale().fitContent();

    return () => {
      macdChart?.remove();
      chart.remove();
    };
  }, [candles, volumes, overlays, macd]);

  // Text equivalent of the canvas: range, endpoints, and direction.
  const chartSummary = useMemo(() => {
    if (bars.length === 0) return "Price chart with no data available.";
    const first = bars[0];
    const last = bars[bars.length - 1];
    const open = Number(first.close);
    const close = Number(last.close);
    const changePct = open === 0 ? 0 : ((close - open) / open) * 100;
    const direction = changePct >= 0 ? "up" : "down";
    const overlayNames = Object.keys(overlays ?? {});
    const withOverlays = overlayNames.length ? ` Overlays: ${overlayNames.join(", ")}.` : "";
    return (
      `Candlestick price chart covering ${bars.length} sessions from ` +
      `${new Date(first.ts).toLocaleDateString("en-US")} to ` +
      `${new Date(last.ts).toLocaleDateString("en-US")}. ` +
      `Closed at ${close.toFixed(2)}, ${direction} ${Math.abs(changePct).toFixed(2)} percent ` +
      `over the period.${withOverlays}`
    );
  }, [bars, overlays]);

  return (
    <div className="space-y-2">
      {/* lightweight-charts renders to a canvas, which is opaque to assistive
          tech. The figure caption carries the same headline facts in text. */}
      <figure className="m-0">
        <div ref={containerRef} className="h-[420px] w-full" role="img" aria-label={chartSummary} />
        <figcaption className="sr-only">{chartSummary}</figcaption>
      </figure>
      {macd?.length ? <div ref={macdRef} className="h-[140px] w-full" /> : null}
    </div>
  );
}
