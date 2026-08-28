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
  type SeriesMarker,
  type Time,
  type UTCTimestamp,
  createChart,
  createSeriesMarkers,
} from "lightweight-charts";
import { useEffect, useMemo, useRef } from "react";

import type { Bar, IndicatorPoint, MACDPoint } from "@/lib/api";
import { useChartPalette } from "@/lib/chart-theme";

export type PriceChartMarker = {
  time: string;
  position: "aboveBar" | "belowBar";
  color: string;
  shape: "arrowUp" | "arrowDown" | "circle";
  text: string;
};

type Props = {
  bars: Bar[];
  overlays?: Record<string, IndicatorPoint[]>;
  macd?: MACDPoint[] | null;
  markers?: PriceChartMarker[];
};

function toUtcSeconds(iso: string): UTCTimestamp {
  return Math.floor(new Date(iso).getTime() / 1000) as UTCTimestamp;
}

export function PriceChart({ bars, overlays, macd, markers }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const macdRef = useRef<HTMLDivElement | null>(null);
  const palette = useChartPalette();

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
        color: Number(b.close) >= Number(b.open) ? palette.positiveFill : palette.negativeFill,
      })),
    [bars, palette],
  );

  useEffect(() => {
    if (!containerRef.current) return;

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

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: palette.positive,
      downColor: palette.negative,
      borderVisible: false,
      wickUpColor: palette.positive,
      wickDownColor: palette.negative,
    });
    candleSeries.setData(candles);
    if (markers?.length) {
      createSeriesMarkers(
        candleSeries,
        markers.map(
          (marker): SeriesMarker<Time> => ({
            time: toUtcSeconds(marker.time),
            position: marker.position,
            color: marker.color,
            shape: marker.shape,
            text: marker.text,
          }),
        ),
      );
    }

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
        color: palette.overlays[colorIdx % palette.overlays.length],
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
          textColor: palette.text,
        },
        grid: {
          vertLines: { color: palette.grid },
          horzLines: { color: palette.grid },
        },
        timeScale: { borderColor: palette.axis, timeVisible: false },
        rightPriceScale: { borderColor: palette.axis },
      });
      const macdLine = macdChart.addSeries(LineSeries, {
        color: palette.overlays[0],
        lineWidth: 2,
        priceLineVisible: false,
        title: "MACD",
      });
      const signalLine = macdChart.addSeries(LineSeries, {
        color: palette.overlays[2],
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
          color: p.histogram >= 0 ? palette.positiveFill : palette.negativeFill,
        })),
      );
    }

    chart.timeScale().fitContent();
    macdChart?.timeScale().fitContent();

    return () => {
      macdChart?.remove();
      chart.remove();
    };
  }, [candles, volumes, overlays, macd, markers, palette]);

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
    const markerText = markers?.length
      ? ` Trade markers: ${markers.map((marker) => `${marker.text} on ${new Date(marker.time).toLocaleDateString("en-US")}`).join("; ")}.`
      : "";
    return (
      `Candlestick price chart covering ${bars.length} bars from ` +
      `${new Date(first.ts).toLocaleDateString("en-US")} to ` +
      `${new Date(last.ts).toLocaleDateString("en-US")}. ` +
      `Closed at ${close.toFixed(2)}, ${direction} ${Math.abs(changePct).toFixed(2)} percent ` +
      `over the period.${withOverlays}${markerText}`
    );
  }, [bars, overlays, markers]);

  return (
    <div className="space-y-2">
      {/* lightweight-charts renders to a canvas, which is opaque to assistive
          tech. The figure caption carries the same headline facts in text. */}
      <figure className="m-0">
        <div
          ref={containerRef}
          className="h-[360px] w-full sm:h-[420px]"
          role="img"
          aria-label={chartSummary}
        />
        <figcaption className="sr-only">{chartSummary}</figcaption>
      </figure>
      {macd?.length ? <div ref={macdRef} className="h-[140px] w-full" /> : null}
    </div>
  );
}
