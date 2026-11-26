import "server-only";

/**
 * A6.8: what each chart workspace pane draws, read on the server like the
 * stock page's chart (`app/(product)/stocks/[ticker]/page.tsx`): the symbol,
 * its bars at the pane's interval, and the template's indicators run on
 * those bars.
 *
 * A pane fails on its own: an unknown symbol is `missing` (a saved layout
 * can name a symbol that is gone), a failed call is `error`, and the other
 * panes still draw. An intraday interval the symbol has no bars for falls
 * back to daily, said in `note`.
 */

import { ApiError, type SymbolDetail, getBars, getIndicators, getSymbol } from "@/lib/api";
import type { ChartTemplate } from "@/lib/api/chart-layouts";
import type { Bar, IndicatorPoint, Indicators, MACDPoint } from "@/lib/api/types";
import { DEFAULT_LOOK, type WorkspacePane } from "@/lib/chart-layouts";
import type { ChartScale, ChartType } from "@/lib/chart-view";
import {
  type ChartPane,
  type ParamBounds,
  type StockInterval,
  barsForLookback,
  chartLayers,
  clipBundleFrom,
  intradayBarsForLookback,
  isIntradayInterval,
  lastSessions,
  macdSeries,
  parseIntradayLookback,
  parseStockIndicators,
  sessionsForLookback,
  studyFor,
} from "@/lib/stock-workspace";

/** Trading days each daily interval looks back over (a year of days, five of weeks). */
const LOOKBACK_DAYS: Record<"1d" | "1wk" | "1mo", number> = { "1d": 252, "1wk": 1260, "1mo": 5000 };

export type PaneView =
  | { status: "missing"; symbol: string }
  | { status: "error"; symbol: string }
  | {
      status: "ok";
      symbol: string;
      name: string;
      interval: StockInterval;
      /** Why the interval differs from the pane's, if it does. */
      note: string | null;
      templateName: string | null;
      chartType: ChartType;
      scale: ChartScale;
      paneHeights: Record<string, number> | null;
      indicators: string[];
      bars: Bar[];
      overlays: Record<string, IndicatorPoint[]>;
      panes: ChartPane[];
      rsi: IndicatorPoint[] | null;
      macd: MACDPoint[] | null;
      rsiKey?: string;
      macdKey?: string;
      timeZone: string;
      sourceFeed: string | null;
    };

export async function loadPaneView(
  pane: WorkspacePane,
  templates: readonly ChartTemplate[],
  bounds: Record<string, readonly ParamBounds[]> | null,
): Promise<PaneView> {
  let symbol: SymbolDetail;
  try {
    symbol = await getSymbol(pane.symbol);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      return { status: "missing", symbol: pane.symbol };
    }
    return { status: "error", symbol: pane.symbol };
  }
  const template = templates.find((t) => t.id === pane.templateId) ?? null;
  const indicators = parseStockIndicators(
    template ? template.indicators.join(",") : DEFAULT_LOOK.indicators.join(","),
    bounds,
  );
  const offered = symbol.intraday?.intervals ?? [];
  const unavailable = isIntradayInterval(pane.interval) && !offered.includes(pane.interval);
  const interval: StockInterval = unavailable ? "1d" : pane.interval;
  const intraday = isIntradayInterval(interval);
  const lookback = intraday ? parseIntradayLookback(undefined, interval) : null;
  const limit =
    intraday && lookback
      ? intradayBarsForLookback(lookback, interval, Boolean(symbol.is_indian))
      : barsForLookback(LOOKBACK_DAYS[interval as "1d" | "1wk" | "1mo"], interval);

  let loaded: Bar[];
  let bundle: Indicators;
  try {
    [loaded, bundle] = await Promise.all([
      intraday
        ? getBars(pane.symbol, { interval, limit }).catch(() => [] as Bar[])
        : getBars(pane.symbol, { interval, limit }),
      indicators.length
        ? getIndicators(pane.symbol, { names: indicators, interval, limit }).catch(
            () => ({ ticker: pane.symbol, series: {}, macd: null, meta: {} }) as Indicators,
          )
        : Promise.resolve({ ticker: pane.symbol, series: {}, macd: null, meta: {} } as Indicators),
    ]);
  } catch {
    return { status: "error", symbol: pane.symbol };
  }
  const bars = intraday && lookback ? lastSessions(loaded, sessionsForLookback(lookback)) : loaded;
  const clipped = intraday && bars.length ? clipBundleFrom(bundle, bars[0].ts) : bundle;
  const rsiKey = indicators.find((k) => studyFor(k)?.key === "rsi");
  const macdKey = indicators.find((k) => studyFor(k)?.key === "macd");
  const { overlays, panes } = chartLayers(clipped, indicators, [rsiKey, macdKey]);
  return {
    status: "ok",
    symbol: pane.symbol,
    name: symbol.name,
    interval,
    note: unavailable ? `No ${pane.interval} bars for ${pane.symbol}; showing daily.` : null,
    templateName: template?.name ?? null,
    chartType: (template?.chart_type ?? DEFAULT_LOOK.chartType) as ChartType,
    scale: (template?.scale ?? DEFAULT_LOOK.scale) as ChartScale,
    paneHeights:
      template && Object.keys(template.pane_heights).length ? template.pane_heights : null,
    indicators,
    bars,
    overlays,
    panes,
    rsi: rsiKey ? (clipped.series[rsiKey] ?? null) : null,
    macd: macdKey ? macdSeries(clipped, macdKey) : null,
    rsiKey,
    macdKey,
    timeZone: symbol.intraday?.time_zone ?? "UTC",
    sourceFeed: intraday ? (bars.at(-1)?.feed ?? symbol.intraday?.feed ?? null) : null,
  };
}
