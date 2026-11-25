import type { IndicatorPoint, MACDPoint } from "@/lib/api/types";
import { type ChartPane, STOCK_INDICATORS } from "@/lib/stock-workspace";

/**
 * Which series go to which pane of the one stock chart (A3.1, M2.1).
 *
 * Every pane lives in one Lightweight Charts instance (`addPane` / series
 * `paneIndex`), so they share one time scale, one crosshair and zoom. The
 * order is fixed: price (with its overlays), volume, RSI, MACD, then each
 * separate-pane indicator from `chartLayers()` in menu order. The price pane
 * cannot collapse; a collapsed pane is left out of the chart and listed so
 * it can be shown again.
 */

export type LineSpec = {
  kind: "line";
  key: string;
  label: string;
  points: IndicatorPoint[];
  colorIndex: number;
};
export type HistogramSpec = {
  kind: "histogram";
  key: string;
  label: string;
  points: IndicatorPoint[];
};
export type SeriesSpec = { kind: "price" } | { kind: "volume" } | LineSpec | HistogramSpec;

export type PaneSpec = {
  /** Stable per kind of pane ("price", "volume", "rsi", "macd", or the indicator name). */
  kind: string;
  label: string;
  series: SeriesSpec[];
  /** Horizontal guides (RSI 70/30). */
  guides: number[];
  defaultHeight: number;
};

export const PRICE_PANE = "price";
export const VOLUME_PANE = "volume";

export const DEFAULT_PANE_HEIGHTS: Record<string, number> = {
  [PRICE_PANE]: 300,
  [VOLUME_PANE]: 80,
  rsi: 110,
  macd: 130,
};
const DEFAULT_INDICATOR_HEIGHT = 100;
/** The smallest a pane is kept at, whatever the stored height says. */
export const MIN_PANE_HEIGHT = 48;

export type PaneInputs = {
  overlays?: Record<string, IndicatorPoint[]>;
  rsi?: IndicatorPoint[] | null;
  macd?: MACDPoint[] | null;
  panes?: ChartPane[];
  showVolume?: boolean;
};

/** "SMA 50", "Bollinger Bands 20, 2 upper": the menu's name plus the output. */
export function overlayLabel(key: string): string {
  const [base, output] = key.split(".");
  const name = STOCK_INDICATORS.find((i) => i.value === base)?.label ?? base.toUpperCase();
  return output ? `${name} ${output}` : name;
}

/** Every pane the inputs ask for, in chart order, collapsed or not. */
export function allPanes({
  overlays,
  rsi,
  macd,
  panes,
  showVolume = true,
}: PaneInputs): PaneSpec[] {
  const out: PaneSpec[] = [];
  const price: SeriesSpec[] = [{ kind: "price" }];
  let colorIndex = 0;
  for (const [key, points] of Object.entries(overlays ?? {})) {
    if (!points.length) continue;
    price.push({ kind: "line", key, label: overlayLabel(key), points, colorIndex });
    colorIndex += 1;
  }
  out.push({
    kind: PRICE_PANE,
    label: "Price",
    series: price,
    guides: [],
    defaultHeight: DEFAULT_PANE_HEIGHTS[PRICE_PANE],
  });
  if (showVolume) {
    out.push({
      kind: VOLUME_PANE,
      label: "Volume",
      series: [{ kind: "volume" }],
      guides: [],
      defaultHeight: DEFAULT_PANE_HEIGHTS[VOLUME_PANE],
    });
  }
  if (rsi?.length) {
    out.push({
      kind: "rsi",
      label: "RSI 14",
      series: [{ kind: "line", key: "rsi_14", label: "RSI 14", points: rsi, colorIndex: 1 }],
      guides: [70, 30],
      defaultHeight: DEFAULT_PANE_HEIGHTS.rsi,
    });
  }
  if (macd?.length) {
    out.push({
      kind: "macd",
      label: "MACD",
      series: [
        {
          kind: "line",
          key: "macd",
          label: "MACD",
          points: macd.map((p) => ({ ts: p.ts, value: p.macd })),
          colorIndex: 0,
        },
        {
          kind: "line",
          key: "macd.signal",
          label: "Signal",
          points: macd.map((p) => ({ ts: p.ts, value: p.signal })),
          colorIndex: 2,
        },
        {
          kind: "histogram",
          key: "macd.histogram",
          label: "Histogram",
          points: macd.map((p) => ({ ts: p.ts, value: p.histogram })),
        },
      ],
      guides: [],
      defaultHeight: DEFAULT_PANE_HEIGHTS.macd,
    });
  }
  for (const pane of panes ?? []) {
    const series: SeriesSpec[] = Object.entries(pane.lines).map(([key, points], index) => ({
      kind: "line",
      key,
      label: key.includes(".") ? `${pane.label} ${key.split(".")[1]}` : pane.label,
      points,
      colorIndex: index,
    }));
    if (!series.length) continue;
    out.push({
      kind: pane.name,
      label: pane.label,
      series,
      guides: [],
      defaultHeight: DEFAULT_INDICATOR_HEIGHT,
    });
  }
  return out;
}

/** The panes drawn and the ones collapsed out of the chart. */
export function assemblePanes(
  inputs: PaneInputs,
  collapsed: ReadonlySet<string> = new Set(),
): { visible: PaneSpec[]; collapsed: PaneSpec[] } {
  const panes = allPanes(inputs);
  return {
    visible: panes.filter((p) => p.kind === PRICE_PANE || !collapsed.has(p.kind)),
    collapsed: panes.filter((p) => p.kind !== PRICE_PANE && collapsed.has(p.kind)),
  };
}

/** A pane's height: the stored one if sane, else its default. */
export function paneHeight(pane: PaneSpec, stored: Record<string, number>): number {
  const value = stored[pane.kind];
  return Number.isFinite(value) && value >= MIN_PANE_HEIGHT
    ? Math.round(value)
    : pane.defaultHeight;
}

// ---- Remembered layout (a convenience only: localStorage may be missing) ----

const STORAGE_KEY = "stockviz:chart-panes";

export type PaneLayout = { heights: Record<string, number>; collapsed: string[] };

export function readPaneLayout(): PaneLayout {
  const empty: PaneLayout = { heights: {}, collapsed: [] };
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return empty;
    const parsed = JSON.parse(raw) as Partial<PaneLayout>;
    const heights: Record<string, number> = {};
    for (const [kind, value] of Object.entries(parsed.heights ?? {})) {
      if (typeof value === "number" && Number.isFinite(value)) heights[kind] = value;
    }
    const collapsed = Array.isArray(parsed.collapsed)
      ? parsed.collapsed.filter((k): k is string => typeof k === "string" && k !== PRICE_PANE)
      : [];
    return { heights, collapsed };
  } catch {
    return empty;
  }
}

export function writePaneLayout(layout: PaneLayout): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(layout));
  } catch {
    // Private mode or blocked storage: the layout just isn't remembered.
  }
}
