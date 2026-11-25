"use client";

/**
 * The price chart: one Lightweight Charts instance with native panes (A3.1,
 * M2.1, M2.3).
 *
 * Price (with its overlays), volume, RSI, MACD and every separate-pane
 * indicator are panes of the same chart (`lib/chart-panes.ts` decides which
 * series go where), so they share one time scale, one crosshair, zoom and
 * pan. A floating legend on the price pane reads the hovered bar, or the
 * last bar when the cursor leaves (`lib/chart-legend.ts`). Pane heights can
 * be dragged and are remembered per pane kind in localStorage, and any pane
 * but price collapses out of the chart.
 *
 * Keyboard, once the chart has focus: arrow keys step the crosshair a bar,
 * Home/End jump to the first/last bar, `+`/`-` zoom, `0` fits every bar,
 * Escape clears. The legend is announced politely, throttled.
 *
 * Indicator values arrive warmed up by the API (Phase 6.1), so RSI on a 1M
 * chart equals RSI on a 1Y chart.
 */

import {
  AreaSeries,
  BarSeries,
  CandlestickSeries,
  CrosshairMode,
  HistogramSeries,
  type IChartApi,
  type ISeriesApi,
  LineSeries,
  type LogicalRange,
  type MouseEventParams,
  PriceScaleMode,
  type SeriesMarker,
  type SeriesType,
  type Time,
  type UTCTimestamp,
  createChart,
  createSeriesMarkers,
} from "lightweight-charts";
import { ChevronDown, ChevronUp } from "lucide-react";
import {
  type KeyboardEvent,
  type PointerEvent as ReactPointerEvent,
  type SyntheticEvent,
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
} from "react";

import type { Bar, IndicatorPoint, MACDPoint } from "@/lib/api";
import { barTimeToUtcSeconds } from "@/lib/api-time";
import { buildLegendModel, legendAt, legendText } from "@/lib/chart-legend";
import {
  PRICE_PANE,
  type PaneLayout,
  type PaneSpec,
  assemblePanes,
  paneHeight,
  readPaneLayout,
  writePaneLayout,
} from "@/lib/chart-panes";
import { fitWithLabelRoom } from "@/lib/chart-range";
import { type ChartPalette, useChartPalette } from "@/lib/chart-theme";
import type { ChartScale, ChartType } from "@/lib/chart-view";
import { barDate } from "@/lib/drawings/anchor";
import { dragPoints, placePoint } from "@/lib/drawings/drag";
import type { DrawingPoint } from "@/lib/drawings/kinds";
import { DrawingsPrimitive } from "@/lib/drawings/primitive";
import { type SceneDrawing, hitScene } from "@/lib/drawings/scene";
import { heikinAshi } from "@/lib/heikin-ashi";
import {
  type ChartPane,
  type StockInterval,
  formatCloseDate,
  partialBarLabel,
} from "@/lib/stock-workspace";

export type PriceChartMarker = {
  time: string;
  position: "aboveBar" | "belowBar";
  color: string;
  shape: "arrowUp" | "arrowDown" | "circle";
  text: string;
};

/**
 * A3.2: the drawings on the price pane and what the pointer does with them.
 * Drawings are drawn by one series primitive (`lib/drawings/primitive.ts`).
 */
export type ChartDrawingLayer = {
  /** Saved drawings plus the one being placed (id "draft"). */
  drawings: SceneDrawing[];
  selectedId: string | null;
  /** A tool is active: a click places its next anchor. */
  placingKind: SceneDrawing["kind"] | null;
  /** Anchors already placed for the tool. */
  placedCount: number;
  onPlace: (point: DrawingPoint) => void;
  /** Where the next anchor would go, while placing (null when the pointer leaves). */
  onPreview: (point: DrawingPoint | null) => void;
  onSelect: (id: string | null) => void;
  onMoved: (id: string, points: DrawingPoint[]) => void;
};

type Props = {
  bars: Bar[];
  overlays?: Record<string, IndicatorPoint[]>;
  macd?: MACDPoint[] | null;
  /** RSI(14) values; drawn in its own pane with 70/30 guides. */
  rsi?: IndicatorPoint[] | null;
  /** Phase 6.6: other separate-pane indicators, one pane each. */
  panes?: ChartPane[];
  markers?: PriceChartMarker[];
  /** A1.4a: the bars' interval; a partial newest weekly/monthly bar is labelled. */
  interval?: StockInterval;
  /** A3.1: how the prices are drawn. */
  chartType?: ChartType;
  scale?: ChartScale;
  showVolume?: boolean;
  drawingLayer?: ChartDrawingLayer;
};

const DRAG_THRESHOLD_PX = 4;

const TIME_AXIS_PX = 28;
const SEPARATOR_PX = 1;
const NARROW_PRICE_PX = 240;
const ANNOUNCE_EVERY_MS = 600;
const ZOOM_STEP = 0.8;

const TYPE_WORDS: Record<ChartType, string> = {
  candles: "Candlestick",
  hollow: "Hollow candlestick",
  bars: "OHLC bar",
  line: "Line",
  area: "Area",
  "heikin-ashi": "Heikin-Ashi (derived from the stored bars)",
};

const SCALE_MODE: Record<ChartScale, PriceScaleMode> = {
  linear: PriceScaleMode.Normal,
  log: PriceScaleMode.Logarithmic,
  percent: PriceScaleMode.Percentage,
};

function toUtcSeconds(iso: string): UTCTimestamp {
  return barTimeToUtcSeconds(iso) as UTCTimestamp;
}

type Candle = { time: UTCTimestamp; open: number; high: number; low: number; close: number };

/** The main price series for a chart type, with its data; `closes` feed the keyboard crosshair. */
function addPriceSeries(
  chart: IChartApi,
  type: ChartType,
  candles: Candle[],
  palette: ChartPalette,
): { series: ISeriesApi<SeriesType>; closes: number[] } {
  if (type === "line" || type === "area") {
    const data = candles.map((c) => ({ time: c.time, value: c.close }));
    const series =
      type === "line"
        ? chart.addSeries(
            LineSeries,
            { color: palette.line, lineWidth: 2, priceLineVisible: false },
            0,
          )
        : chart.addSeries(
            AreaSeries,
            {
              lineColor: palette.line,
              topColor: palette.areaTop,
              bottomColor: palette.areaBottom,
              lineWidth: 2,
              priceLineVisible: false,
            },
            0,
          );
    series.setData(data);
    return { series, closes: data.map((d) => d.value) };
  }
  if (type === "bars") {
    const series = chart.addSeries(
      BarSeries,
      { upColor: palette.positive, downColor: palette.negative, thinBars: false },
      0,
    );
    series.setData(candles);
    return { series, closes: candles.map((c) => c.close) };
  }
  const data = type === "heikin-ashi" ? heikinAshi(candles) : candles;
  const hollow = type === "hollow";
  const series = chart.addSeries(
    CandlestickSeries,
    {
      // Hollow: rising candles are outlines, falling ones filled.
      upColor: hollow ? "rgba(0, 0, 0, 0)" : palette.positive,
      downColor: palette.negative,
      borderVisible: hollow,
      borderUpColor: palette.positive,
      borderDownColor: palette.negative,
      wickUpColor: palette.positive,
      wickDownColor: palette.negative,
    },
    0,
  );
  series.setData(data);
  return { series, closes: data.map((c) => c.close) };
}

export function PriceChart({
  bars,
  overlays,
  macd,
  rsi,
  panes,
  markers,
  interval = "1d",
  chartType = "candles",
  scale = "linear",
  showVolume = true,
  drawingLayer,
}: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const mainRef = useRef<{ series: ISeriesApi<SeriesType>; closes: number[] } | null>(null);
  const rangeRef = useRef<{ count: number; range: LogicalRange } | null>(null);
  const palette = useChartPalette();
  const primitiveRef = useRef<DrawingsPrimitive | null>(null);
  const layerRef = useRef<ChartDrawingLayer | undefined>(drawingLayer);
  layerRef.current = drawingLayer;
  const hasLayer = drawingLayer !== undefined;
  const barDates = useMemo(() => bars.map((b) => barDate(b.ts)), [bars]);

  // Remembered layout: read after mount (localStorage is the browser's), and
  // the chart waits for it so it is built once.
  const [layout, setLayout] = useState<PaneLayout | null>(null);
  const heightsRef = useRef<Record<string, number>>({});
  useEffect(() => {
    const stored = readPaneLayout();
    heightsRef.current = stored.heights;
    setLayout(stored);
  }, []);
  const collapsedSet = useMemo(() => new Set(layout?.collapsed ?? []), [layout]);

  const { visible, collapsed } = useMemo(
    () => assemblePanes({ overlays, rsi, macd, panes, showVolume }, collapsedSet),
    [overlays, rsi, macd, panes, showVolume, collapsedSet],
  );
  const legendModel = useMemo(() => buildLegendModel(bars, visible), [bars, visible]);
  const seriesColour = useMemo(() => {
    const map = new Map<string, string>();
    for (const pane of visible) {
      for (const s of pane.series) {
        if (s.kind === "line")
          map.set(s.key, palette.overlays[s.colorIndex % palette.overlays.length]);
      }
    }
    return map;
  }, [visible, palette]);

  const candles = useMemo<Candle[]>(
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
  const indexByTime = useMemo(
    () => new Map(candles.map((c, i) => [c.time as number, i])),
    [candles],
  );

  const [hoverIndex, setHoverIndex] = useState<number | null>(null);
  const [keyIndex, setKeyIndex] = useState<number | null>(null);
  const keyIndexRef = useRef<number | null>(null);
  keyIndexRef.current = keyIndex;
  const [paneTops, setPaneTops] = useState<number[]>([]);

  const measurePanes = useCallback(() => {
    const chart = chartRef.current;
    if (!chart) return;
    const tops: number[] = [];
    let top = 0;
    for (const pane of chart.panes()) {
      tops.push(top);
      top += pane.getHeight() + SEPARATOR_PX;
    }
    setPaneTops(tops);
  }, []);

  useEffect(() => {
    const el = containerRef.current;
    if (!el || layout === null) return;

    const narrow = el.clientWidth > 0 && el.clientWidth < 640;
    const heights = visible.map((pane) => {
      const height = paneHeight(pane, heightsRef.current);
      return pane.kind === PRICE_PANE && narrow && heightsRef.current[PRICE_PANE] === undefined
        ? NARROW_PRICE_PX
        : height;
    });
    el.style.height = `${heights.reduce((a, b) => a + b, 0) + (visible.length - 1) * SEPARATOR_PX + TIME_AXIS_PX}px`;

    const chart = createChart(el, {
      autoSize: true,
      layout: {
        background: { color: "transparent" },
        textColor: palette.text,
        panes: {
          enableResize: true,
          separatorColor: palette.axis,
          separatorHoverColor: palette.grid,
        },
      },
      grid: { vertLines: { color: palette.grid }, horzLines: { color: palette.grid } },
      timeScale: { borderColor: palette.axis, timeVisible: false },
      rightPriceScale: { borderColor: palette.axis },
      crosshair: { mode: CrosshairMode.Normal },
    });
    chartRef.current = chart;

    visible.forEach((pane, paneIndex) => {
      let guideHost: ISeriesApi<SeriesType> | null = null;
      for (const spec of pane.series) {
        if (spec.kind === "price") {
          const main = addPriceSeries(chart, chartType, candles, palette);
          mainRef.current = main;
          main.series.priceScale().applyOptions({ mode: SCALE_MODE[scale] });
          if (hasLayer) {
            const primitive = new DrawingsPrimitive();
            main.series.attachPrimitive(primitive);
            primitiveRef.current = primitive;
          }
          if (markers?.length) {
            createSeriesMarkers(
              main.series,
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
        } else if (spec.kind === "volume") {
          const volume = chart.addSeries(
            HistogramSeries,
            { priceFormat: { type: "volume" }, lastValueVisible: false, priceLineVisible: false },
            paneIndex,
          );
          volume.setData(
            bars.map((b) => ({
              time: toUtcSeconds(b.ts),
              value: b.volume,
              color:
                Number(b.close) >= Number(b.open) ? palette.positiveFill : palette.negativeFill,
            })),
          );
        } else if (spec.kind === "line") {
          const line = chart.addSeries(
            LineSeries,
            {
              color: palette.overlays[spec.colorIndex % palette.overlays.length],
              lineWidth: 2,
              priceLineVisible: false,
              lastValueVisible: pane.kind !== PRICE_PANE,
            },
            paneIndex,
          );
          line.setData(spec.points.map((p) => ({ time: toUtcSeconds(p.ts), value: p.value })));
          guideHost ??= line;
        } else {
          const histogram = chart.addSeries(
            HistogramSeries,
            { priceLineVisible: false, lastValueVisible: false },
            paneIndex,
          );
          histogram.setData(
            spec.points.map((p) => ({
              time: toUtcSeconds(p.ts),
              value: p.value,
              color: p.value >= 0 ? palette.positiveFill : palette.negativeFill,
            })),
          );
        }
      }
      for (const level of pane.guides) {
        guideHost?.createPriceLine({
          price: level,
          color: palette.axis,
          lineWidth: 1,
          lineStyle: 2,
          axisLabelVisible: true,
          title: "",
        });
      }
    });
    chart.panes().forEach((pane, i) => {
      pane.setStretchFactor(heights[i] ?? 1);
      // Log and percent belong to the price pane only. Without this the
      // volume and indicator panes followed it and weekly volume drew flat.
      if (i > 0) {
        for (const series of pane.getSeries()) {
          series.priceScale().applyOptions({ mode: PriceScaleMode.Normal });
        }
      }
    });

    // Keep the zoom across a rebuild of the same bars (a collapse, a type change).
    const kept = rangeRef.current;
    if (kept && kept.count === candles.length) chart.timeScale().setVisibleLogicalRange(kept.range);
    else fitWithLabelRoom(chart, candles.length, el.clientWidth - 64);

    const onMove = (param: MouseEventParams<Time>) => {
      if (param.time === undefined) {
        setHoverIndex(keyIndexRef.current);
        return;
      }
      setHoverIndex(indexByTime.get(param.time as number) ?? null);
    };
    chart.subscribeCrosshairMove(onMove);
    const frame =
      typeof requestAnimationFrame === "function" ? requestAnimationFrame(measurePanes) : 0;

    return () => {
      if (frame && typeof cancelAnimationFrame === "function") cancelAnimationFrame(frame);
      const range = chart.timeScale().getVisibleLogicalRange?.();
      rangeRef.current = range ? { count: candles.length, range } : null;
      chart.unsubscribeCrosshairMove(onMove);
      chart.remove();
      chartRef.current = null;
      mainRef.current = null;
      primitiveRef.current = null;
    };
  }, [
    candles,
    bars,
    visible,
    markers,
    palette,
    chartType,
    scale,
    layout,
    indexByTime,
    measurePanes,
    hasLayer,
  ]);

  // ---- Drawings (A3.2) ----
  const fontRef = useRef("sans-serif");
  const pushDrawings = useCallback(
    (override?: SceneDrawing[]) => {
      const layer = layerRef.current;
      const primitive = primitiveRef.current;
      if (!layer || !primitive) return;
      if (containerRef.current && typeof getComputedStyle === "function") {
        fontRef.current = getComputedStyle(containerRef.current).fontFamily || "sans-serif";
      }
      primitive.setState({
        drawings: override ?? layer.drawings,
        selectedId: layer.selectedId,
        interval,
        barDates,
        palette,
        fontFamily: fontRef.current,
      });
    },
    [interval, barDates, palette],
  );
  // biome-ignore lint/correctness/useExhaustiveDependencies: a rebuilt chart (new candles, layout, type) needs the drawings again.
  useEffect(() => {
    pushDrawings();
  }, [
    pushDrawings,
    drawingLayer?.drawings,
    drawingLayer?.selectedId,
    candles,
    layout,
    chartType,
    scale,
    visible,
  ]);

  type Grab = {
    id: string;
    handle: number | null;
    start: { logical: number; price: number };
    startX: number;
    startY: number;
    points: DrawingPoint[];
    kind: SceneDrawing["kind"];
    moved: DrawingPoint[] | null;
  };
  const grabRef = useRef<Grab | null>(null);
  const downRef = useRef<{ x: number; y: number } | null>(null);

  /** Pointer position in the price pane, or null outside it. */
  const panePoint = useCallback((clientX: number, clientY: number) => {
    const el = containerRef.current;
    const chart = chartRef.current;
    if (!el || !chart) return null;
    const rect = el.getBoundingClientRect();
    const x = clientX - rect.left;
    const y = clientY - rect.top;
    const width = chart.timeScale().width();
    const height = chart.panes()[0]?.getHeight() ?? 0;
    if (x < 0 || y < 0 || x > width || y > height) return null;
    return { x, y };
  }, []);

  const onDrawingPointerDown = useCallback(
    (event: ReactPointerEvent<HTMLDivElement>) => {
      const layer = layerRef.current;
      const primitive = primitiveRef.current;
      if (!layer || !primitive || event.button !== 0) return;
      downRef.current = { x: event.clientX, y: event.clientY };
      if (layer.placingKind) return;
      const at = panePoint(event.clientX, event.clientY);
      if (!at) return;
      const hit = hitScene(primitive.shapes, at.x, at.y);
      if (!hit || hit.id === "draft") return;
      const drawing = layer.drawings.find((d) => d.id === hit.id);
      const start = primitive.toChart(at.x, at.y);
      if (!drawing || drawing.locked || !start) return;
      // Only the selected drawing moves; a first press selects it.
      if (layer.selectedId !== drawing.id) return;
      grabRef.current = {
        id: drawing.id,
        handle: hit.handle,
        start,
        startX: event.clientX,
        startY: event.clientY,
        points: drawing.points,
        kind: drawing.kind,
        moved: null,
      };
    },
    [panePoint],
  );

  // Keep Lightweight Charts from panning while a drawing is grabbed: it
  // listens for mouse and touch events, which follow the pointer event.
  const stopIfGrabbed = useCallback((event: SyntheticEvent) => {
    if (grabRef.current) event.stopPropagation();
  }, []);

  useEffect(() => {
    if (!hasLayer) return;
    const onMove = (event: PointerEvent) => {
      const layer = layerRef.current;
      const primitive = primitiveRef.current;
      const grab = grabRef.current;
      if (!layer || !primitive) return;
      if (grab) {
        if (
          !grab.moved &&
          Math.hypot(event.clientX - grab.startX, event.clientY - grab.startY) < DRAG_THRESHOLD_PX
        )
          return;
        const el = containerRef.current;
        if (!el) return;
        const rect = el.getBoundingClientRect();
        const now = primitive.toChart(event.clientX - rect.left, event.clientY - rect.top);
        if (!now) return;
        grab.moved = dragPoints(
          grab.kind,
          grab.points,
          grab.handle,
          grab.start,
          now,
          interval,
          barDates,
        );
        pushDrawings(
          layer.drawings.map((d) =>
            d.id === grab.id ? { ...d, points: grab.moved ?? d.points } : d,
          ),
        );
        return;
      }
      if (layer.placingKind) {
        const at = panePoint(event.clientX, event.clientY);
        const chartAt = at ? primitive.toChart(at.x, at.y) : null;
        layer.onPreview(
          chartAt ? placePoint(layer.placingKind, layer.placedCount, chartAt, barDates) : null,
        );
      }
    };
    const onUp = (event: PointerEvent) => {
      const layer = layerRef.current;
      const primitive = primitiveRef.current;
      const grab = grabRef.current;
      const down = downRef.current;
      grabRef.current = null;
      downRef.current = null;
      if (!layer || !primitive) return;
      if (grab?.moved) {
        layer.onMoved(grab.id, grab.moved);
        return;
      }
      if (!down || Math.hypot(event.clientX - down.x, event.clientY - down.y) >= DRAG_THRESHOLD_PX)
        return;
      const at = panePoint(event.clientX, event.clientY);
      if (!at) return;
      if (layer.placingKind) {
        const chartAt = primitive.toChart(at.x, at.y);
        const point = chartAt
          ? placePoint(layer.placingKind, layer.placedCount, chartAt, barDates)
          : null;
        if (point) layer.onPlace(point);
        return;
      }
      const hit = hitScene(primitive.shapes, at.x, at.y);
      layer.onSelect(hit && hit.id !== "draft" ? hit.id : null);
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    return () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
    };
  }, [hasLayer, interval, barDates, panePoint, pushDrawings]);

  // After a separator drag, remember each pane's new height (no rebuild).
  const rememberHeights = useCallback(() => {
    const chart = chartRef.current;
    if (!chart) return;
    const heights = { ...heightsRef.current };
    let changed = false;
    chart.panes().forEach((pane, i) => {
      const kind = visible[i]?.kind;
      const height = pane.getHeight();
      if (kind && height > 0 && Math.abs((heights[kind] ?? 0) - height) > 1) {
        heights[kind] = height;
        changed = true;
      }
    });
    if (changed) {
      heightsRef.current = heights;
      writePaneLayout({ heights, collapsed: layout?.collapsed ?? [] });
    }
    measurePanes();
  }, [visible, layout, measurePanes]);

  const toggleCollapsed = useCallback((kind: string) => {
    setLayout((current) => {
      const base = current ?? { heights: {}, collapsed: [] };
      const next = base.collapsed.includes(kind)
        ? base.collapsed.filter((k) => k !== kind)
        : [...base.collapsed, kind];
      const updated = { heights: heightsRef.current, collapsed: next };
      writePaneLayout(updated);
      return updated;
    });
  }, []);

  // ---- Keyboard ----
  const moveTo = useCallback(
    (index: number) => {
      const chart = chartRef.current;
      const main = mainRef.current;
      if (!chart || !main || !candles.length) return;
      const i = Math.max(0, Math.min(candles.length - 1, index));
      setKeyIndex(i);
      setHoverIndex(i);
      chart.setCrosshairPosition(main.closes[i], candles[i].time, main.series);
      const range = chart.timeScale().getVisibleLogicalRange();
      if (range && (i < range.from || i > range.to)) {
        const width = range.to - range.from;
        const from = i < range.from ? i - 1 : i - width + 1;
        chart.timeScale().setVisibleLogicalRange({ from, to: from + width });
      }
    },
    [candles],
  );

  const zoom = useCallback((factor: number) => {
    const chart = chartRef.current;
    const range = chart?.timeScale().getVisibleLogicalRange();
    if (!chart || !range) return;
    const centre = keyIndexRef.current ?? (range.from + range.to) / 2;
    const half = Math.max(2, ((range.to - range.from) / 2) * factor);
    chart.timeScale().setVisibleLogicalRange({ from: centre - half, to: centre + half });
  }, []);

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const current = keyIndexRef.current ?? candles.length - 1;
    const chart = chartRef.current;
    let handled = true;
    if (event.key === "ArrowLeft") moveTo(current - 1);
    else if (event.key === "ArrowRight") moveTo(current + 1);
    else if (event.key === "Home") moveTo(0);
    else if (event.key === "End") moveTo(candles.length - 1);
    else if (event.key === "+" || event.key === "=") zoom(ZOOM_STEP);
    else if (event.key === "-" || event.key === "_") zoom(1 / ZOOM_STEP);
    else if (event.key === "0" && chart) {
      fitWithLabelRoom(chart, candles.length, (containerRef.current?.clientWidth ?? 0) - 64);
    } else if (event.key === "Escape") {
      setKeyIndex(null);
      setHoverIndex(null);
      chart?.clearCrosshairPosition();
    } else handled = false;
    if (handled) event.preventDefault();
  };

  const legend = legendAt(legendModel, hoverIndex);

  // The legend in words, announced politely and at most every ANNOUNCE_EVERY_MS,
  // only while the chart has keyboard focus.
  const [announcement, setAnnouncement] = useState("");
  const lastAnnounceRef = useRef(0);
  const announceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const legendSentence = legend ? legendText(legend) : "";
  useEffect(() => {
    if (keyIndex === null || !legendSentence) return;
    const wait = Math.max(0, lastAnnounceRef.current + ANNOUNCE_EVERY_MS - Date.now());
    if (announceTimerRef.current) clearTimeout(announceTimerRef.current);
    announceTimerRef.current = setTimeout(() => {
      lastAnnounceRef.current = Date.now();
      setAnnouncement(legendSentence);
    }, wait);
    return () => {
      if (announceTimerRef.current) clearTimeout(announceTimerRef.current);
    };
  }, [keyIndex, legendSentence]);

  const partialLabel = partialBarLabel(bars.at(-1), interval);

  // Text equivalent of the canvas: range, endpoints, direction, panes.
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
    const paneText = visible.length > 1 ? ` Panes: ${visible.map((p) => p.label).join(", ")}.` : "";
    const scaleText =
      scale === "linear" ? "" : ` ${scale === "log" ? "Logarithmic" : "Percent"} scale.`;
    const partialText = partialLabel ? ` ${partialLabel}` : "";
    const markerText = markers?.length
      ? ` Trade markers: ${markers.map((marker) => `${marker.text} on ${formatCloseDate(marker.time) ?? marker.time}`).join("; ")}.`
      : "";
    return (
      `${TYPE_WORDS[chartType]} price chart covering ${bars.length} bars from ` +
      `${formatCloseDate(first.ts) ?? first.ts} to ` +
      `${formatCloseDate(last.ts) ?? last.ts}. ` +
      `Closed at ${close.toFixed(2)}, ${direction} ${Math.abs(changePct).toFixed(2)} percent ` +
      `over the period.${scaleText}${withOverlays}${paneText}${markerText}${partialText}`
    );
  }, [bars, overlays, markers, partialLabel, visible, chartType, scale]);

  const helpId = useId();

  return (
    <div className="space-y-2">
      <figure className="m-0">
        {/* Focusable for the keyboard path; pointer-up saves dragged pane heights. */}
        <div
          // biome-ignore lint/a11y/useSemanticElements: a fieldset is for form controls; this is a canvas widget.
          role="group"
          // biome-ignore lint/a11y/noNoninteractiveTabindex: the chart takes keys (arrows, +, -, 0).
          tabIndex={0}
          aria-label="Interactive price chart"
          aria-describedby={helpId}
          onKeyDown={onKeyDown}
          onPointerUp={rememberHeights}
          onPointerDownCapture={hasLayer ? onDrawingPointerDown : undefined}
          onMouseDownCapture={hasLayer ? stopIfGrabbed : undefined}
          onTouchStartCapture={hasLayer ? stopIfGrabbed : undefined}
          onBlur={() => setKeyIndex(null)}
          className="relative rounded-sm outline-none focus-visible:ring-2 focus-visible:ring-brand/60"
          data-testid="price-chart"
          data-pane-count={visible.length}
          data-panes={visible.map((p) => p.kind).join(",")}
          data-drawing-count={
            drawingLayer ? drawingLayer.drawings.filter((d) => d.id !== "draft").length : undefined
          }
          data-drawing-tool={drawingLayer?.placingKind ?? undefined}
          style={drawingLayer?.placingKind ? { cursor: "crosshair" } : undefined}
        >
          {/* lightweight-charts renders to a canvas, which is opaque to
              assistive tech; the caption and legend carry the facts in text. */}
          <div
            ref={containerRef}
            className="h-[408px] w-full sm:h-[468px]"
            role="img"
            aria-label={chartSummary}
          />
          {legend ? (
            <div
              className="pointer-events-none absolute top-1.5 left-2 z-10 max-w-[calc(100%-5rem)] rounded-sm bg-card/80 px-1.5 py-1 text-2xs leading-4 text-text-secondary backdrop-blur-[2px]"
              data-testid="chart-legend"
              data-bar-index={legend.index}
              data-last={legend.isLast ? "true" : "false"}
            >
              <div className="flex flex-wrap items-baseline gap-x-2 font-mono">
                <span className="font-sans font-medium text-foreground">{legend.date}</span>
                {chartType === "heikin-ashi" ? (
                  <span className="font-sans text-text-tertiary">
                    HA candles derived; stored prices
                  </span>
                ) : null}
                <span>
                  O <span className="text-foreground">{legend.open}</span>
                </span>
                <span>
                  H <span className="text-foreground">{legend.high}</span>
                </span>
                <span>
                  L <span className="text-foreground">{legend.low}</span>
                </span>
                <span>
                  C <span className="text-foreground">{legend.close}</span>
                </span>
                <span
                  className={
                    legend.direction === 1
                      ? "text-positive"
                      : legend.direction === -1
                        ? "text-negative"
                        : "text-text-secondary"
                  }
                >
                  {legend.change} ({legend.changePct})
                </span>
                <span>
                  Vol <span className="text-foreground">{legend.volume}</span>
                </span>
              </div>
              {legend.indicators.length ? (
                <div
                  className="mt-0.5 flex flex-wrap gap-x-2.5 font-mono"
                  data-testid="chart-legend-indicators"
                >
                  {legend.indicators.map((ind) => (
                    <span key={ind.key}>
                      <span
                        className="font-sans"
                        style={
                          seriesColour.get(ind.key)
                            ? { color: seriesColour.get(ind.key) }
                            : undefined
                        }
                      >
                        {ind.label}
                      </span>{" "}
                      <span className="text-foreground">{ind.value}</span>
                    </span>
                  ))}
                </div>
              ) : null}
            </div>
          ) : null}
          {visible.map((pane, i) =>
            pane.kind === PRICE_PANE ? null : (
              <PaneHeader
                key={pane.kind}
                pane={pane}
                top={paneTops[i] ?? 0}
                onCollapse={() => toggleCollapsed(pane.kind)}
              />
            ),
          )}
        </div>
        <figcaption className="sr-only">{chartSummary}</figcaption>
      </figure>
      <p className="sr-only" aria-live="polite" data-testid="chart-announcement">
        {announcement}
      </p>
      {collapsed.length ? (
        <div className="flex flex-wrap items-center gap-1.5 px-1" aria-label="Collapsed panes">
          {collapsed.map((pane) => (
            <button
              key={pane.kind}
              type="button"
              onClick={() => toggleCollapsed(pane.kind)}
              aria-expanded={false}
              className="inline-flex h-7 items-center gap-1 rounded-sm border border-border-muted px-2 text-2xs text-text-secondary transition-colors hover:bg-surface-hover hover:text-foreground"
              data-testid={`show-pane-${pane.kind}`}
            >
              <ChevronDown className="size-3" aria-hidden />
              Show {pane.label}
            </button>
          ))}
        </div>
      ) : null}
      {partialLabel ? (
        <p className="px-1 text-2xs text-text-tertiary" data-testid="partial-bar-label">
          {partialLabel}
        </p>
      ) : null}
      <details className="px-1 text-2xs text-text-tertiary">
        <summary className="cursor-pointer select-none hover:text-text-secondary">
          Chart keys and panes
        </summary>
        <p id={helpId} className="mt-1 leading-5">
          Focus the chart, then: left and right arrows move one bar, Home and End jump to the first
          and last bar, + and − zoom, 0 fits every bar, Escape clears the crosshair. The legend
          reads the bar under the crosshair, or the last bar. Drag the line between two panes to
          resize them; heights are remembered in this browser. Collapse a pane with its arrow.
        </p>
      </details>
    </div>
  );
}

/** A pane's name and its collapse control, at the pane's top-left. */
function PaneHeader({
  pane,
  top,
  onCollapse,
}: { pane: PaneSpec; top: number; onCollapse: () => void }) {
  return (
    <div
      className="absolute left-2 z-10 flex items-center gap-1 text-2xs text-text-tertiary"
      style={{ top: top + 4 }}
      data-testid={`pane-${pane.kind}`}
    >
      <span className="rounded-sm bg-card/80 px-1">{pane.label}</span>
      <button
        type="button"
        onClick={onCollapse}
        aria-expanded={true}
        aria-label={`Collapse the ${pane.label} pane`}
        title={`Collapse ${pane.label}`}
        className="inline-flex size-5 items-center justify-center rounded-sm bg-card/80 text-text-tertiary transition-colors hover:bg-surface-hover hover:text-foreground"
      >
        <ChevronUp className="size-3" aria-hidden />
      </button>
    </div>
  );
}
