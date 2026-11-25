/**
 * A recording stand-in for `lightweight-charts` (A3.1): jsdom has no canvas.
 *
 *   vi.mock("lightweight-charts", async () => (await import("../stubs/lightweight-charts")).lwc);
 *
 * Every chart, series, pane, price line and crosshair call lands in `lwcCalls`
 * so tests can assert which series went to which pane of the one chart.
 */

import { vi } from "vitest";

type Handler = (param: { time?: number }) => void;

export type RecordedSeries = {
  type: string;
  options: Record<string, unknown>;
  pane: number;
  data: unknown[];
  priceLines: number[];
  scaleOptions: Record<string, unknown>[];
};

export const lwcCalls = {
  charts: 0,
  removed: 0,
  series: [] as RecordedSeries[],
  stretch: [] as number[],
  crosshair: [] as { price: number; time: number }[],
  handlers: [] as Handler[],
  visibleRanges: [] as { from: number; to: number }[],
  /** A3.2: series primitives attached (the drawings host). */
  primitives: [] as unknown[],
};

export function resetLwc(): void {
  lwcCalls.charts = 0;
  lwcCalls.removed = 0;
  lwcCalls.series = [];
  lwcCalls.stretch = [];
  lwcCalls.crosshair = [];
  lwcCalls.handlers = [];
  lwcCalls.visibleRanges = [];
  lwcCalls.primitives = [];
}

/** Fire the newest chart's crosshair handler, as a hover would. */
export function hover(time: number | undefined): void {
  for (const handler of lwcCalls.handlers) handler({ time });
}

function createChart() {
  lwcCalls.charts += 1;
  const mine: RecordedSeries[] = [];
  const apis: { pane: number; api: unknown }[] = [];
  let range = { from: 0, to: 10 };
  const chart = {
    addSeries(type: string, options: Record<string, unknown> = {}, pane = 0) {
      const record: RecordedSeries = {
        type,
        options,
        pane,
        data: [],
        priceLines: [],
        scaleOptions: [],
      };
      lwcCalls.series.push(record);
      mine.push(record);
      const api = {
        setData: (data: unknown[]) => {
          record.data = data;
        },
        createPriceLine: ({ price }: { price: number }) => record.priceLines.push(price),
        priceScale: () => ({
          applyOptions: (o: Record<string, unknown>) => record.scaleOptions.push(o),
        }),
        // A3.2: price = 200 - y, so a test can predict coordinates.
        priceToCoordinate: (price: number) => 200 - price,
        coordinateToPrice: (y: number) => 200 - y,
        attachPrimitive: (primitive: { attached?: (p: unknown) => void }) => {
          lwcCalls.primitives.push(primitive);
          primitive.attached?.({ chart, series: api, requestUpdate: () => {} });
        },
        detachPrimitive: vi.fn(),
      };
      apis.push({ pane, api });
      return api;
    },
    panes() {
      const count = mine.reduce((n, s) => Math.max(n, s.pane + 1), 1);
      return Array.from({ length: count }, (_, index) => ({
        setStretchFactor: (n: number) => lwcCalls.stretch.push(n),
        getHeight: () => 100,
        getSeries: () => apis.filter((a) => a.pane === index).map((a) => a.api),
      }));
    },
    priceScale: () => ({ applyOptions: vi.fn() }),
    applyOptions: vi.fn(),
    timeScale: () => ({
      fitContent: vi.fn(),
      width: () => 0,
      // A3.2: ten pixels a bar.
      logicalToCoordinate: (logical: number) => logical * 10,
      coordinateToLogical: (x: number) => x / 10,
      getVisibleLogicalRange: () => range,
      setVisibleLogicalRange: (r: { from: number; to: number }) => {
        range = r;
        lwcCalls.visibleRanges.push(r);
      },
    }),
    subscribeCrosshairMove: (h: Handler) => lwcCalls.handlers.push(h),
    unsubscribeCrosshairMove: (h: Handler) => {
      lwcCalls.handlers = lwcCalls.handlers.filter((x) => x !== h);
    },
    setCrosshairPosition: (price: number, time: number) => lwcCalls.crosshair.push({ price, time }),
    clearCrosshairPosition: vi.fn(),
    remove: () => {
      lwcCalls.removed += 1;
    },
  };
  return chart;
}

export const lwc = {
  AreaSeries: "AreaSeries",
  BarSeries: "BarSeries",
  CandlestickSeries: "CandlestickSeries",
  HistogramSeries: "HistogramSeries",
  LineSeries: "LineSeries",
  CrosshairMode: { Normal: 0, Magnet: 1 },
  PriceScaleMode: { Normal: 0, Logarithmic: 1, Percentage: 2, IndexedTo100: 3 },
  createSeriesMarkers: vi.fn(),
  createChart,
};
