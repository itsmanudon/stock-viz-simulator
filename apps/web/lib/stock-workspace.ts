import type { Bar, IndicatorPoint } from "@/lib/api/types";

const QUANTITY_SCALE = 1_000_000;

export const STOCK_TIMEFRAMES = ["1M", "3M", "6M", "1Y", "5Y", "MAX"] as const;
/**
 * The chart's indicator menu (Phase 6.6): names from the API's engine
 * registry (`/v1/indicators/catalog`), with their usual parameters. Where each
 * one draws comes from the API's `meta.pane`, not from this list, so adding an
 * entry here is all a new indicator needs.
 */
export const STOCK_INDICATORS = [
  { value: "sma_20", label: "SMA 20", section: "price" },
  { value: "sma_50", label: "SMA 50", section: "price" },
  { value: "sma_200", label: "SMA 200", section: "price" },
  { value: "ema_50", label: "EMA 50", section: "price" },
  { value: "bb_20_2", label: "Bollinger Bands 20, 2", section: "price" },
  { value: "keltner_20_2_10", label: "Keltner Channels", section: "price" },
  { value: "donchian_20", label: "Donchian Channels 20", section: "price" },
  { value: "vwap_20", label: "VWAP 20 (rolling)", section: "price" },
  { value: "supertrend_10_3", label: "Supertrend 10, 3", section: "price" },
  { value: "rsi_14", label: "RSI 14", section: "pane" },
  { value: "macd", label: "MACD", section: "pane" },
  { value: "stoch_14_3", label: "Stochastic 14, 3", section: "pane" },
  { value: "adx_14", label: "ADX 14", section: "pane" },
  { value: "atr_14", label: "ATR 14", section: "pane" },
  { value: "cci_20", label: "CCI 20", section: "pane" },
  { value: "mfi_14", label: "MFI 14", section: "pane" },
  { value: "obv", label: "OBV", section: "pane" },
  { value: "rvol_20", label: "Relative volume 20", section: "pane" },
] as const;

export type ChartPane = { name: string; label: string; lines: Record<string, IndicatorPoint[]> };

/**
 * Split an indicator bundle into price-chart overlays and separate panes by
 * each indicator's registry pane (Phase 6.6). RSI and MACD keep their own
 * panes; Supertrend's direction output is a state, not a line, so it is left
 * out of the overlay.
 */
export function chartLayers(
  bundle: {
    series: Record<string, IndicatorPoint[]>;
    meta?: Record<string, { pane: string; label: string }>;
  },
  selected: readonly string[],
): { overlays: Record<string, IndicatorPoint[]>; panes: ChartPane[] } {
  const overlays: Record<string, IndicatorPoint[]> = {};
  const panes: ChartPane[] = [];
  for (const name of selected) {
    if (name === "rsi_14" || name === "macd") continue;
    const meta = bundle.meta?.[name];
    const keys = Object.keys(bundle.series).filter((k) => k === name || k.startsWith(`${name}.`));
    if (!keys.length) continue;
    if ((meta?.pane ?? "price") === "price") {
      for (const key of keys) {
        if (!key.endsWith(".direction")) overlays[key] = bundle.series[key];
      }
    } else {
      panes.push({
        name,
        label: meta?.label ?? name,
        lines: Object.fromEntries(keys.map((k) => [k, bundle.series[k]])),
      });
    }
  }
  return { overlays, panes };
}

export type StockTimeframe = (typeof STOCK_TIMEFRAMES)[number];
export type StockIndicator = (typeof STOCK_INDICATORS)[number]["value"];

export function parseStockIndicators(raw: string | undefined): StockIndicator[] {
  if (raw === undefined) return ["sma_50"];
  if (raw === "") return [];
  const valid = new Set(STOCK_INDICATORS.map((indicator) => indicator.value));
  return raw
    .split(",")
    .map((value) => value.trim())
    .filter((value): value is StockIndicator => valid.has(value as StockIndicator));
}

export function buildStockChartHref(
  ticker: string,
  timeframe: StockTimeframe,
  indicators: StockIndicator[],
): string {
  const params = new URLSearchParams();
  params.set("tf", timeframe);
  params.set("indicators", indicators.join(","));
  return `/stocks/${ticker}?${params.toString()}`;
}

export function formatQuantity(value: number | string): string {
  const numericValue = Number(value);
  if (!Number.isFinite(numericValue)) return "—";
  return new Intl.NumberFormat("en-US", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 6,
    useGrouping: true,
  }).format(numericValue);
}

function isPositiveFinite(value: number): boolean {
  return Number.isFinite(value) && value > 0;
}

function quantityString(value: number): string | null {
  if (!isPositiveFinite(value)) return null;
  const floored = Math.floor((value + Number.EPSILON) * QUANTITY_SCALE) / QUANTITY_SCALE;
  if (floored <= 0) return null;
  return floored.toFixed(6).replace(/\.?0+$/, "");
}

export function getBuyShortcutQuantity({
  availableCash,
  price,
  fraction,
  symbolCurrency,
  displayCurrency,
}: {
  availableCash: number;
  price: number;
  fraction: number;
  symbolCurrency: string;
  displayCurrency: string;
}): string | null {
  if (
    symbolCurrency !== displayCurrency ||
    !isPositiveFinite(availableCash) ||
    !isPositiveFinite(price) ||
    !isPositiveFinite(fraction) ||
    fraction > 1
  ) {
    return null;
  }
  return quantityString((availableCash * fraction) / price);
}

export function getSellShortcutQuantity({
  availableQuantity,
  fraction,
}: {
  availableQuantity: number;
  fraction: number;
}): string | null {
  if (!isPositiveFinite(availableQuantity) || !isPositiveFinite(fraction) || fraction > 1) {
    return null;
  }
  return quantityString(availableQuantity * fraction);
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/**
 * "Apr 4, 2025" for a stored bar timestamp. Reads the calendar date straight
 * from the string, so the label never shifts a day with the server's or the
 * browser's timezone (UI audit T2), and always carries the year (T3).
 */
export function formatCloseDate(iso: string | null | undefined): string | null {
  const match = iso ? /^(\d{4})-(\d{2})-(\d{2})/.exec(iso) : null;
  if (!match) return null;
  const month = MONTHS[Number(match[2]) - 1];
  return month ? `${month} ${Number(match[3])}, ${match[1]}` : null;
}

export type TicketOrderMode = "market" | "limit" | "stop_loss" | "take_profit";

/**
 * How the simulator fills each order type, in the words the order review
 * shows. Mirrors docs/OPERATIONAL_TRADING.md: market orders fill at once at
 * the latest stored daily close; pending orders are checked against the daily
 * close by the weekday 16:45 ET job and fill at that close, not at the trigger.
 */
export function describeFillRule(mode: TicketOrderMode): string {
  if (mode === "market") return "Fills now at the latest stored daily close";
  const trigger = mode === "limit" ? "your limit" : "your trigger";
  return `Checked after each weekday close (16:45 ET). Fills at that close once it reaches ${trigger}, not at ${trigger} itself`;
}

export function estimateNotional(quantity: number, price: number): number | null {
  if (!isPositiveFinite(quantity) || !isPositiveFinite(price)) return null;
  return quantity * price;
}

export function calculatePositionReturnPct(
  unrealizedPnl: number,
  costBasis: number,
): number | null {
  if (!Number.isFinite(unrealizedPnl) || !isPositiveFinite(costBasis)) return null;
  return (unrealizedPnl / costBasis) * 100;
}

export function calculateAllocationPct(marketValue: number, totalValue: number): number | null {
  if (!Number.isFinite(marketValue) || !isPositiveFinite(totalValue)) return null;
  return (marketValue / totalValue) * 100;
}

export function calculatePeriodReturnPct(
  firstClose: number | null,
  latestClose: number | null,
): number | null {
  if (
    firstClose === null ||
    latestClose === null ||
    !isPositiveFinite(firstClose) ||
    !Number.isFinite(latestClose)
  ) {
    return null;
  }
  return ((latestClose - firstClose) / firstClose) * 100;
}

export type BarMetrics = {
  open: number | null;
  high: number | null;
  low: number | null;
  previousClose: number | null;
  volume: number | null;
  rangeHigh: number | null;
  rangeLow: number | null;
  latestTimestamp: string | null;
};

function numeric(value: string): number | null {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

export function deriveBarMetrics(bars: Bar[]): BarMetrics {
  const latest = bars.at(-1);
  if (!latest) {
    return {
      open: null,
      high: null,
      low: null,
      previousClose: null,
      volume: null,
      rangeHigh: null,
      rangeLow: null,
      latestTimestamp: null,
    };
  }

  const highs = bars.map((entry) => Number(entry.high)).filter(Number.isFinite);
  const lows = bars.map((entry) => Number(entry.low)).filter(Number.isFinite);
  const previous = bars.at(-2);

  return {
    open: numeric(latest.open),
    high: numeric(latest.high),
    low: numeric(latest.low),
    previousClose: previous ? numeric(previous.close) : null,
    volume: Number.isFinite(latest.volume) ? latest.volume : null,
    rangeHigh: highs.length ? Math.max(...highs) : null,
    rangeLow: lows.length ? Math.min(...lows) : null,
    latestTimestamp: latest.ts,
  };
}

export function deriveTrailingBarMetrics(bars: Bar[], window = 252): BarMetrics {
  return deriveBarMetrics(bars.slice(-window));
}
