import type { Bar } from "@/lib/api/types";

const QUANTITY_SCALE = 1_000_000;

export const STOCK_TIMEFRAMES = ["1M", "3M", "6M", "1Y", "5Y", "MAX"] as const;
export const STOCK_INDICATORS = [
  { value: "sma_20", label: "SMA 20" },
  { value: "sma_50", label: "SMA 50" },
  { value: "sma_200", label: "SMA 200" },
  { value: "ema_50", label: "EMA 50" },
  { value: "rsi_14", label: "RSI 14" },
  { value: "macd", label: "MACD" },
] as const;

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
