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
import { ChevronDown, ChevronUp, X } from "lucide-react";
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

import { useLiveBars } from "@/components/use-live-bars";
import type { Bar, IndicatorPoint, MACDPoint } from "@/lib/api";
import { barTimeToUtcSeconds } from "@/lib/api-time";
import {
  type ChartEvent,
  EVENT_LETTER,
  eventKey,
  eventSummary,
  eventsByBar,
  formatR,
  legendEvents,
} from "@/lib/chart-events";
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
import { sessionDateOf } from "@/lib/drawings/anchor";
import { dragPoints, placePoint } from "@/lib/drawings/drag";
import type { DrawingPoint } from "@/lib/drawings/kinds";
import { DrawingsPrimitive } from "@/lib/drawings/primitive";
import { type SceneDrawing, hitScene } from "@/lib/drawings/scene";
import { heikinAshi } from "@/lib/heikin-ashi";
import type { IndicatorBadge } from "@/lib/indicator-badge";
import { liveStatusText } from "@/lib/live-bars";
import { SessionBreaksPrimitive, sessionStarts } from "@/lib/session-breaks";
import {
  type ChartPane,
  type StockInterval,
  dateInZone,
  formatBarTime,
  formatCloseDate,
  indicatorLabel,
  isIntradayInterval,
  partialBarLabel,
  sourceBadgeLabel,
  sourceBadgeTitle,
  splitSeriesKey,
  studyFor,
  timeInZone,
  zoneLabel,
} from "@/lib/stock-workspace";

export type PriceChartMarker = {
  time: string;
  position: "aboveBar" | "belowBar";
  color: string;
  shape: "arrowUp" | "arrowDown" | "circle";
  text: string;
  /**
   * Fold this label into the fill marker on the same bar and side ("S · MAE
   * -0.41%") instead of stacking a second marker there. Drawn on its own when
   * no fill marker sits there.
   */
  mergeIntoFill?: boolean;
};

/** A5.5: a horizontal level on the price pane (a plan's entry, stop, target). */
export type PriceChartLine = {
  price: number;
  title: string;
  color: string;
  dashed?: boolean;
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

/**
 * A6.7: the built chart's parts, for tools that live outside this file (the
 * volume profile, the context menu, plan lines). Handed to `onChartReady`
 * each time the chart is built.
 */
export type PriceChartHandle = {
  chart: IChartApi;
  /** The price series (primitives and price lines attach to it). */
  series: ISeriesApi<SeriesType>;
  /** The focusable chart group (pointer and key events). */
  root: HTMLElement;
  /** The canvas container: price-pane coordinates start at its top-left. */
  container: HTMLElement;
  bars: Bar[];
  /** The saved drawing under a price-pane point, if any. */
  drawingAt: (x: number, y: number) => SceneDrawing | null;
  drawings: () => readonly SceneDrawing[];
  /** A6.5's stream is delivering bars (not replayed ones). */
  streaming: () => boolean;
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
  /** A3.4: the chart keys drawn in the RSI and MACD panes (`rsi_21`, `macd_8_21_5`). */
  rsiKey?: string;
  macdKey?: string;
  /** A3.4: evidence badges by chart key, shown beside each study in the legend. */
  badges?: Record<string, IndicatorBadge>;
  /**
   * A3.5: chart events already filtered to the shown types (news, earnings,
   * dividends, splits, the viewer's fills): markers on the price pane, a
   * popover on click (or Enter), the legend and the "Chart events" list.
   */
  events?: ChartEvent[];
  /** The symbol's currency, for dividend amounts. */
  currency?: string;
  /** A5.5: labelled levels on the price pane (the journal's plan lines). */
  priceLines?: PriceChartLine[];
  /**
   * A6.2, intraday intervals: the venue's IANA zone the axis, crosshair and
   * legend read times in (bars stay UTC instants), default UTC.
   */
  timeZone?: string;
  /** A6.2: the intraday feed, shown as the chart's source badge. */
  sourceFeed?: string | null;
  /**
   * A6.5: on an intraday interval, the ticker whose stored minute bars stream
   * in (server-sent events from the stream worker); null keeps the chart still.
   */
  liveTicker?: string | null;
  /** A6.7: called with the chart's parts each time it is built; may return a cleanup. */
  onChartReady?: (handle: PriceChartHandle) => (() => void) | undefined;
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
  bars: serverBars,
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
  rsiKey,
  macdKey,
  badges,
  events,
  currency,
  priceLines,
  timeZone = "UTC",
  sourceFeed,
  liveTicker = null,
  onChartReady,
}: Props) {
  const intraday = isIntradayInterval(interval);
  const live = useLiveBars(intraday ? liveTicker : null, serverBars, interval, timeZone);
  const bars = live.bars;
  const containerRef = useRef<HTMLDivElement | null>(null);
  // A6.7: the chart's parts go to tools outside this file (`onChartReady`).
  const rootRef = useRef<HTMLDivElement | null>(null);
  const readyRef = useRef(onChartReady);
  readyRef.current = onChartReady;
  const streamingRef = useRef(false);
  streamingRef.current = live.status === "live" && !live.replayed;
  const chartRef = useRef<IChartApi | null>(null);
  const mainRef = useRef<{ series: ISeriesApi<SeriesType>; closes: number[] } | null>(null);
  const rangeRef = useRef<{ count: number; range: LogicalRange } | null>(null);
  const palette = useChartPalette();
  const primitiveRef = useRef<DrawingsPrimitive | null>(null);
  const layerRef = useRef<ChartDrawingLayer | undefined>(drawingLayer);
  layerRef.current = drawingLayer;
  const hasLayer = drawingLayer !== undefined;
  // Each bar's session date: drawings, events and session breaks key on it.
  const barDates = useMemo(() => bars.map(sessionDateOf), [bars]);
  // A6.2: the bars that open a new session (dashed breaks on intraday charts).
  const breakStarts = useMemo(
    () => (intraday ? sessionStarts(barDates) : []),
    [intraday, barDates],
  );
  const formatBarLabel = useCallback(
    (ts: string) => (intraday ? formatBarTime(ts, timeZone) : (formatCloseDate(ts) ?? ts)),
    [intraday, timeZone],
  );

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
    () => assemblePanes({ overlays, rsi, macd, panes, showVolume, rsiKey, macdKey }, collapsedSet),
    [overlays, rsi, macd, panes, showVolume, rsiKey, macdKey, collapsedSet],
  );
  const legendModel = useMemo(() => buildLegendModel(bars, visible), [bars, visible]);
  const priceKeys = useMemo(
    () =>
      new Set(
        visible
          .filter((pane) => pane.kind === PRICE_PANE)
          .flatMap((pane) => pane.series.map((spec) => ("key" in spec ? spec.key : ""))),
      ),
    [visible],
  );
  // A3.4: each study's badge once, on its first series in the legend.
  const badgeKeys = useMemo(() => {
    const map = new Map<string, IndicatorBadge>();
    const seen = new Set<string>();
    for (const ind of legendModel.indicators) {
      const base = splitSeriesKey(ind.key)[0];
      const badge = badges?.[base];
      if (badge && !seen.has(base)) {
        seen.add(base);
        map.set(ind.key, badge);
      }
    }
    return map;
  }, [legendModel, badges]);
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

  // A3.5: events per bar (the drawings' period rule), and their markers.
  const byBar = useMemo(
    () => eventsByBar(events ?? [], interval, barDates),
    [events, interval, barDates],
  );
  const allMarkers = useMemo<SeriesMarker<Time>[]>(() => {
    const colour: Record<ChartEvent["type"], string> = {
      news: palette.drawing.violet,
      earnings: palette.drawing.amber,
      dividend: palette.drawing.lime,
      split: palette.drawing.blue,
      fill: palette.drawing.foreground,
    };
    const out: SeriesMarker<Time>[] = [];
    for (const [index, list] of byBar) {
      const time = candles[index]?.time;
      if (time === undefined) continue;
      const seen = new Set<string>();
      for (const event of list) {
        if (event.type === "fill") {
          out.push({
            id: `event:${index}:fill:${event.ts}`,
            time,
            position: event.side === "sell" ? "aboveBar" : "belowBar",
            color: colour.fill,
            shape: event.side === "sell" ? "arrowDown" : "arrowUp",
            // A5.5: the fill that closes a journal entry carries its R.
            text:
              event.r_multiple !== null && event.r_multiple !== undefined
                ? `${event.side === "sell" ? "S" : "B"} ${formatR(event.r_multiple)}`
                : event.side === "sell"
                  ? "S"
                  : "B",
          });
          continue;
        }
        if (seen.has(event.type)) continue;
        seen.add(event.type);
        const newsCount = list
          .filter((e) => e.type === "news")
          .reduce((n, e) => n + (e.type === "news" ? e.count : 0), 0);
        out.push({
          id: `event:${index}:${event.type}`,
          time,
          position: "aboveBar",
          color: colour[event.type],
          shape: "circle",
          text: event.type === "news" ? String(newsCount) : EVENT_LETTER[event.type],
        });
      }
    }
    for (const marker of markers ?? []) {
      const time = toUtcSeconds(marker.time);
      const fill = marker.mergeIntoFill
        ? out.find(
            (m) =>
              m.time === time &&
              m.position === marker.position &&
              String(m.id ?? "").includes(":fill:"),
          )
        : undefined;
      if (fill) {
        fill.text = `${fill.text} · ${marker.text}`;
        continue;
      }
      out.push({
        time,
        position: marker.position,
        color: marker.color,
        shape: marker.shape,
        text: marker.text,
      });
    }
    return out.sort((a, b) => (a.time as number) - (b.time as number));
  }, [markers, byBar, candles, palette]);
  const [openEvents, setOpenEvents] = useState<{ index: number; x: number } | null>(null);
  const openEventsRef = useRef(setOpenEvents);
  openEventsRef.current = setOpenEvents;
  const byBarRef = useRef(byBar);
  byBarRef.current = byBar;

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
      // A6.2: intraday charts drop the vertical grid so the dashed session
      // breaks are the only vertical lines.
      grid: {
        vertLines: { color: palette.grid, visible: !intraday },
        horzLines: { color: palette.grid },
      },
      timeScale: {
        borderColor: palette.axis,
        timeVisible: intraday,
        secondsVisible: false,
        // A6.2: intraday ticks in the venue's zone; a day mark opens each session.
        ...(intraday
          ? {
              tickMarkFormatter: (time: Time, tickType: number) => {
                const ms = (time as number) * 1000;
                if (tickType <= 2)
                  return formatCloseDate(dateInZone(ms, timeZone))?.replace(/, \d{4}$/, "") ?? null;
                return timeInZone(ms, timeZone);
              },
            }
          : {}),
      },
      ...(intraday
        ? {
            localization: {
              timeFormatter: (time: Time) =>
                `${formatCloseDate(dateInZone((time as number) * 1000, timeZone))} ${timeInZone((time as number) * 1000, timeZone)} ${zoneLabel(timeZone)}`,
            },
          }
        : {}),
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
          if (allMarkers.length) createSeriesMarkers(main.series, allMarkers);
          // A6.2: a faint line where one session ends and the next opens.
          if (intraday && breakStarts.length) {
            main.series.attachPrimitive(new SessionBreaksPrimitive(breakStarts, palette.text));
          }
          for (const line of priceLines ?? []) {
            main.series.createPriceLine({
              price: line.price,
              color: line.color,
              lineWidth: 1,
              lineStyle: line.dashed ? 2 : 0,
              axisLabelVisible: true,
              title: line.title,
            });
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
              // A3.4: Parabolic SAR is a row of dots, not a line.
              ...(spec.dots
                ? { lineVisible: false, pointMarkersVisible: true, pointMarkersRadius: 1.5 }
                : {}),
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
    // A3.5: a click on a bar with events opens its list (not while placing a drawing).
    const onClick = (param: MouseEventParams<Time>) => {
      if (layerRef.current?.placingKind) return;
      const index = param.time === undefined ? undefined : indexByTime.get(param.time as number);
      if (index === undefined || !byBarRef.current.has(index)) {
        openEventsRef.current(null);
        return;
      }
      const x = chart.timeScale().timeToCoordinate(param.time as Time) ?? 0;
      openEventsRef.current({ index, x });
    };
    chart.subscribeClick(onClick);
    const main = mainRef.current;
    const detach =
      main && rootRef.current
        ? readyRef.current?.({
            chart,
            series: main.series,
            root: rootRef.current,
            container: el,
            bars,
            drawingAt: (x, y) => {
              const hit = primitiveRef.current ? hitScene(primitiveRef.current.shapes, x, y) : null;
              if (!hit || hit.id === "draft") return null;
              return layerRef.current?.drawings.find((d) => d.id === hit.id) ?? null;
            },
            drawings: () => layerRef.current?.drawings ?? [],
            streaming: () => streamingRef.current,
          })
        : undefined;
    const frame =
      typeof requestAnimationFrame === "function" ? requestAnimationFrame(measurePanes) : 0;

    return () => {
      if (frame && typeof cancelAnimationFrame === "function") cancelAnimationFrame(frame);
      const range = chart.timeScale().getVisibleLogicalRange?.();
      rangeRef.current = range ? { count: candles.length, range } : null;
      chart.unsubscribeCrosshairMove(onMove);
      chart.unsubscribeClick(onClick);
      detach?.();
      chart.remove();
      chartRef.current = null;
      mainRef.current = null;
      primitiveRef.current = null;
    };
  }, [
    candles,
    bars,
    visible,
    allMarkers,
    palette,
    chartType,
    scale,
    layout,
    indexByTime,
    measurePanes,
    hasLayer,
    priceLines,
    intraday,
    timeZone,
    breakStarts,
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
    } else if (event.key === "Enter" && byBar.has(current)) {
      const time = candles[current]?.time;
      const x = time === undefined ? 0 : (chart?.timeScale().timeToCoordinate(time) ?? 0);
      setOpenEvents({ index: current, x });
    } else if (event.key === "Escape" && openEvents) {
      setOpenEvents(null);
    } else if (event.key === "Escape") {
      setKeyIndex(null);
      setHoverIndex(null);
      chart?.clearCrosshairPosition();
    } else handled = false;
    if (handled) event.preventDefault();
  };

  const legend = legendAt(legendModel, hoverIndex, formatBarLabel);
  const legendEventText = legend ? legendEvents(byBar.get(legend.index) ?? []) : "";

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

  const partialLabel = partialBarLabel(bars.at(-1), interval, timeZone);

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
    const eventCount = [...byBar.values()].reduce((n, list) => n + list.length, 0);
    const eventText = eventCount
      ? ` ${eventCount} chart ${eventCount === 1 ? "event" : "events"} marked; see the Chart events list.`
      : "";
    return (
      `${TYPE_WORDS[chartType]} price chart covering ${bars.length} bars from ` +
      `${formatBarLabel(first.ts)} to ` +
      `${formatBarLabel(last.ts)}. ` +
      `Closed at ${close.toFixed(2)}, ${direction} ${Math.abs(changePct).toFixed(2)} percent ` +
      `over the period.${scaleText}${withOverlays}${paneText}${markerText}${eventText}${partialText}`
    );
  }, [bars, overlays, markers, byBar, partialLabel, visible, chartType, scale, formatBarLabel]);

  const helpId = useId();

  return (
    <div className="space-y-2">
      {intraday ? (
        <div
          className="flex flex-wrap items-center gap-x-2 gap-y-1 px-1 text-2xs text-text-tertiary"
          data-testid="chart-source"
        >
          {sourceBadgeLabel(sourceFeed) ? (
            <span
              className="inline-flex h-5 items-center rounded-sm border border-border-muted bg-surface-elevated px-1.5 font-medium tracking-[0.02em] text-text-secondary"
              title={sourceBadgeTitle(sourceFeed)}
              data-testid="chart-source-badge"
              data-feed={sourceFeed ?? undefined}
            >
              <span className="sr-only">Source: </span>
              {sourceBadgeLabel(sourceFeed)}
            </span>
          ) : null}
          {live.status ? (
            <span
              className="inline-flex items-center gap-1"
              data-testid="chart-live-status"
              data-status={live.status}
              aria-live="polite"
            >
              <span
                aria-hidden="true"
                className={`size-1.5 rounded-full ${
                  live.status === "live"
                    ? live.replayed
                      ? "bg-text-tertiary"
                      : "bg-positive"
                    : live.status === "offline"
                      ? "bg-negative"
                      : "bg-border-muted"
                }`}
              />
              {liveStatusText(live.status, live.lastAt, live.replayed, timeZone)}
            </span>
          ) : null}
          <span data-testid="chart-time-zone">
            Times in {zoneLabel(timeZone)}
            {zoneLabel(timeZone) !== timeZone ? ` (${timeZone})` : ""}; bars open at the time shown,
            and nights and weekends take no space.
          </span>
        </div>
      ) : null}
      <figure className="m-0">
        {/* Focusable for the keyboard path; pointer-up saves dragged pane heights. */}
        <div
          ref={rootRef}
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
          data-session-breaks={intraday ? breakStarts.length : undefined}
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
                  {groupLegend(legend.indicators).map((group) => (
                    <span
                      key={group.base}
                      // On a phone the legend keeps to the price pane's own
                      // studies; a lower pane's values are on its axis.
                      className={
                        priceKeys.has(group.items[0].key)
                          ? "inline-flex flex-wrap items-baseline gap-x-1"
                          : "hidden flex-wrap items-baseline gap-x-1 sm:inline-flex"
                      }
                      data-testid="legend-study"
                    >
                      {group.items.length > 1 ? (
                        <span className="font-sans text-text-secondary">{group.label}</span>
                      ) : null}
                      {group.items.map((ind) => (
                        <span key={ind.key} className="inline-flex items-baseline gap-1">
                          <span
                            className="font-sans"
                            style={
                              seriesColour.get(ind.key)
                                ? { color: seriesColour.get(ind.key) }
                                : undefined
                            }
                          >
                            {group.items.length > 1 ? ind.short : ind.label}
                          </span>{" "}
                          <span className="text-foreground">{ind.value}</span>
                        </span>
                      ))}
                      {badgeKeys.get(group.items[0].key) ? (
                        <LegendBadge badge={badgeKeys.get(group.items[0].key) as IndicatorBadge} />
                      ) : null}
                    </span>
                  ))}
                </div>
              ) : null}
              {legendEventText ? (
                <div className="mt-0.5 font-sans text-text-secondary" data-testid="legend-events">
                  Events: <span className="text-foreground">{legendEventText}</span>
                </div>
              ) : null}
            </div>
          ) : null}
          {openEvents && byBar.get(openEvents.index) ? (
            <EventPopover
              date={barDates[openEvents.index] ?? ""}
              events={byBar.get(openEvents.index) ?? []}
              x={openEvents.x}
              currency={currency}
              interval={interval}
              onClose={() => setOpenEvents(null)}
            />
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
      {events !== undefined ? <ChartEventsList events={events} currency={currency} /> : null}
      <details className="px-1 text-2xs text-text-tertiary">
        <summary className="cursor-pointer select-none hover:text-text-secondary">
          Chart keys and panes
        </summary>
        <p id={helpId} className="mt-1 leading-5">
          Focus the chart, then: left and right arrows move one bar, Home and End jump to the first
          and last bar, + and − zoom, 0 fits every bar, Escape clears the crosshair. The legend
          reads the bar under the crosshair, or the last bar. Drag the line between two panes to
          resize them; heights are remembered in this browser. Collapse a pane with its arrow.
          Markers above the bars are events (N news with its count, E earnings, D ex-dividend, S
          split; B and S arrows are your fills): click one, or press Enter on its bar, to list them.
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

/** Short names for a study's outputs in the legend (A3.4). */
const OUTPUT_SHORT: Record<string, string> = {
  senkou_a: "span A",
  senkou_b: "span B",
  plus_di: "+DI",
  minus_di: "−DI",
  plus: "+VI",
  minus: "−VI",
  histogram: "hist",
};

/**
 * The legend's values grouped by study (A3.4): a study with several outputs
 * (Ichimoku, Bollinger, MACD) is one entry with its label once, so the
 * legend stays short enough to leave the price pane readable on a phone.
 */
export function groupLegend(indicators: { key: string; label: string; value: string }[]) {
  const groups: {
    base: string;
    label: string;
    items: { key: string; label: string; short: string; value: string }[];
  }[] = [];
  for (const ind of indicators) {
    const [base, output] = splitSeriesKey(ind.key);
    let group = groups.find((g) => g.base === base);
    if (!group) {
      // A3.5: a pane that is not a registry study (delivery) keeps its own label.
      group = { base, label: studyFor(base) ? indicatorLabel(base) : ind.label, items: [] };
      groups.push(group);
    }
    group.items.push({
      ...ind,
      short: output ? (OUTPUT_SHORT[output] ?? output.replace(/_/g, " ")) : "",
    });
  }
  return groups;
}

/** A3.4: a study's evidence grade in the legend; the whole story in its title. */
function LegendBadge({ badge }: { badge: IndicatorBadge }) {
  return (
    <span
      // Hidden on phones, where the legend has to leave the pane readable;
      // the Indicators menu shows every badge there.
      className={
        badge.graded
          ? "hidden whitespace-nowrap rounded-sm border border-border px-1 font-sans text-3xs text-foreground sm:inline"
          : "hidden whitespace-nowrap rounded-sm border border-border-muted px-1 font-sans text-3xs text-text-tertiary sm:inline"
      }
      title={badge.title}
      data-testid="legend-badge"
    >
      {badge.graded ? `Grade ${badge.text}` : badge.text}
      <span className="sr-only"> {badge.title}</span>
    </span>
  );
}

/** A3.5: the events on one bar, opened by a click on its marker (or Enter). */
function EventPopover({
  date,
  events,
  x,
  currency,
  interval,
  onClose,
}: {
  date: string;
  events: ChartEvent[];
  x: number;
  currency?: string;
  interval: StockInterval;
  onClose: () => void;
}) {
  const ref = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    ref.current?.focus();
  }, []);
  const period = interval === "1wk" ? "Week of" : interval === "1mo" ? "Month of" : "";
  return (
    <div
      ref={ref}
      // biome-ignore lint/a11y/useSemanticElements: a non-modal popover over the canvas, not a modal <dialog>.
      role="dialog"
      aria-label={`Chart events on ${formatCloseDate(date) ?? date}`}
      tabIndex={-1}
      onKeyDown={(event) => {
        if (event.key === "Escape") {
          event.stopPropagation();
          onClose();
        }
      }}
      className="absolute top-10 z-20 w-72 max-w-[calc(100%-1rem)] rounded-md border border-border bg-surface-elevated p-3 text-xs shadow-lg outline-none"
      style={{ left: `clamp(0.5rem, calc(${Math.round(x)}px - 9rem), calc(100% - 18.5rem))` }}
      data-testid="event-popover"
    >
      <div className="flex items-start justify-between gap-2">
        <p className="font-medium text-foreground">
          {period ? `${period} ` : ""}
          {formatCloseDate(date) ?? date}
        </p>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close chart events"
          className="inline-flex size-6 items-center justify-center rounded-sm text-text-tertiary hover:bg-surface-hover hover:text-foreground"
        >
          <X className="size-3.5" aria-hidden />
        </button>
      </div>
      <ul className="mt-1.5 space-y-2">
        {events.map((event, i) => (
          <EventItem key={eventKey(event, i)} event={event} currency={currency} />
        ))}
      </ul>
    </div>
  );
}

/** One event: a line, and for news its headlines (date, source, link; no text). */
function EventItem({ event, currency }: { event: ChartEvent; currency?: string }) {
  return (
    <li data-testid="event-item" data-type={event.type}>
      <p className="text-text-secondary">
        <span className="text-text-tertiary">{formatCloseDate(event.date) ?? event.date} · </span>
        {eventSummary(event, currency)}
      </p>
      {event.type === "news" && event.headlines.length ? (
        <ul className="mt-1 space-y-1 border-l border-border-muted pl-2">
          {event.headlines.map((h) => (
            <li key={h.id} className="leading-4">
              {h.url ? (
                <a
                  href={h.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-foreground hover:underline"
                >
                  {h.title}
                </a>
              ) : (
                <span className="text-foreground">{h.title}</span>
              )}
              <span className="text-text-tertiary"> · {h.source ?? "Unknown source"}</span>
            </li>
          ))}
          {event.count > event.headlines.length ? (
            <li className="text-text-tertiary">
              and {event.count - event.headlines.length} more in the News tab
            </li>
          ) : null}
        </ul>
      ) : null}
    </li>
  );
}

/** A3.5: the keyboard and screen-reader path to every marker: the same items as a list. */
function ChartEventsList({ events, currency }: { events: ChartEvent[]; currency?: string }) {
  return (
    <details className="px-1 text-2xs text-text-tertiary" data-testid="chart-events">
      <summary className="cursor-pointer select-none hover:text-text-secondary">
        Chart events ({events.length})
      </summary>
      {events.length ? (
        <ul className="mt-1.5 max-h-72 space-y-2 overflow-y-auto text-xs">
          {[...events].reverse().map((event, i) => (
            <EventItem key={eventKey(event, i)} event={event} currency={currency} />
          ))}
        </ul>
      ) : (
        <p className="mt-1">No events of the shown types in this range.</p>
      )}
    </details>
  );
}
