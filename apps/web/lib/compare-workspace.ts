import type { Bar } from "@/lib/api";

export const COMPARE_TIMEFRAMES = [
  { value: "1M", days: 22 },
  { value: "3M", days: 65 },
  { value: "6M", days: 130 },
  { value: "1Y", days: 252 },
  { value: "5Y", days: 1260 },
] as const;

export type CompareTimeframe = (typeof COMPARE_TIMEFRAMES)[number]["value"];

export const COMPARE_MAX_SYMBOLS = 6;
export const SAMPLE_COMPARE_TICKERS = ["AAPL", "MSFT", "GOOGL", "AMZN"] as const;

export const COMPARE_SERIES_COLORS = [
  "#3b82f6",
  "#a855f7",
  "#d3a83f",
  "#187c59",
  "#d946ef",
  "#0ea5e9",
] as const;

export type CompareSearchParams = {
  tickers?: string;
  symbols?: string;
  tf?: string;
};

export type CompareMetrics = {
  ticker: string;
  name: string;
  sector: string | null;
  color: string;
  bars: Bar[];
  lastPrice: number | null;
  returnPct: number | null;
  volatilityPct: number | null;
  maxDrawdownPct: number | null;
  rsi14: number | null;
  week52PositionPct: number | null;
  sentiment7d: number | null;
};

export type CompareInsight = {
  id: string;
  text: string;
};

export function parseCompareTickers(raw: string | undefined): string[] {
  if (!raw) return [];
  return Array.from(
    new Set(
      raw
        .split(",")
        .map((ticker) => ticker.trim().toUpperCase())
        .filter(Boolean),
    ),
  ).slice(0, COMPARE_MAX_SYMBOLS);
}

export function parseCompareSearchParams(params: CompareSearchParams): {
  tickers: string[];
  timeframe: CompareTimeframe;
} {
  const tickers = parseCompareTickers(params.tickers ?? params.symbols);
  return { tickers, timeframe: parseCompareTimeframe(params.tf) };
}

export function parseCompareTimeframe(raw: string | undefined): CompareTimeframe {
  return COMPARE_TIMEFRAMES.find((item) => item.value === raw)?.value ?? "1Y";
}

export function compareTimeframeDays(timeframe: CompareTimeframe): number {
  return COMPARE_TIMEFRAMES.find((item) => item.value === timeframe)?.days ?? 252;
}

export function buildCompareHref(
  tickers: string[],
  timeframe: CompareTimeframe,
  extra?: { symbolsAlias?: boolean },
): string {
  const params = new URLSearchParams();
  if (tickers.length) {
    params.set(extra?.symbolsAlias ? "symbols" : "tickers", tickers.join(","));
  }
  params.set("tf", timeframe);
  return `/compare?${params.toString()}`;
}

export function seriesColor(index: number): string {
  return COMPARE_SERIES_COLORS[index % COMPARE_SERIES_COLORS.length];
}

export function closesFromBars(bars: Bar[]): number[] {
  return bars.map((bar) => Number(bar.close)).filter((value) => Number.isFinite(value));
}

export function rangeReturnPct(closes: number[]): number | null {
  if (closes.length < 2) return null;
  const first = closes[0];
  const last = closes[closes.length - 1];
  if (first === 0) return null;
  return ((last - first) / first) * 100;
}

export function annualizedVolatilityPct(closes: number[]): number | null {
  if (closes.length < 3) return null;
  const returns: number[] = [];
  for (let i = 1; i < closes.length; i++) {
    if (closes[i - 1] === 0) continue;
    returns.push(closes[i] / closes[i - 1] - 1);
  }
  if (returns.length < 2) return null;
  const mean = returns.reduce((sum, value) => sum + value, 0) / returns.length;
  const variance =
    returns.reduce((sum, value) => sum + (value - mean) ** 2, 0) / (returns.length - 1);
  if (variance < 0) return null;
  return Math.sqrt(variance) * Math.sqrt(252) * 100;
}

export function maxDrawdownPct(closes: number[]): number | null {
  if (closes.length < 2) return null;
  let peak = closes[0];
  let worst = 0;
  for (const close of closes) {
    if (close > peak) peak = close;
    if (peak > 0) worst = Math.max(worst, (peak - close) / peak);
  }
  return worst * 100;
}

export function week52PositionPct(
  last: number | null,
  low: number | null,
  high: number | null,
): number | null {
  if (last === null || low === null || high === null) return null;
  const span = high - low;
  if (span <= 0) return null;
  return ((last - low) / span) * 100;
}

export function deriveCompareInsights(rows: CompareMetrics[]): CompareInsight[] {
  if (rows.length === 0) return [];
  if (rows.length === 1) {
    const [row] = rows;
    const insights: CompareInsight[] = [
      {
        id: "single-symbol",
        text: `Only ${row.ticker} is selected — add another symbol to compare relative performance.`,
      },
    ];
    if (row.returnPct !== null) {
      insights.push({
        id: "single-return",
        text: `${row.ticker} returned ${formatSignedPct(row.returnPct)} over the selected window.`,
      });
    }
    if (row.bars.length === 0) {
      insights.push({
        id: "missing-history",
        text: `No stored daily bars for ${row.ticker} in this window.`,
      });
    }
    return insights;
  }

  const insights: CompareInsight[] = [];
  const withReturn = rows.filter((row) => row.returnPct !== null);
  if (withReturn.length > 0) {
    const ranked = [...withReturn].sort((a, b) => (b.returnPct ?? 0) - (a.returnPct ?? 0));
    const leader = ranked[0];
    const laggard = ranked[ranked.length - 1];
    insights.push({
      id: "leader",
      text: `${leader.ticker} led the window at ${formatSignedPct(leader.returnPct ?? 0)}.`,
    });
    if (laggard.ticker !== leader.ticker) {
      insights.push({
        id: "laggard",
        text: `${laggard.ticker} lagged at ${formatSignedPct(laggard.returnPct ?? 0)}.`,
      });
    }
  }

  const missing = rows.filter((row) => row.bars.length === 0).map((row) => row.ticker);
  if (missing.length) {
    insights.push({
      id: "missing-history",
      text: `No stored daily bars for ${joinTickers(missing)} in this window.`,
    });
  }

  const withRsi = rows.filter((row) => row.rsi14 !== null);
  if (withRsi.length > 1) {
    const ranked = [...withRsi].sort((a, b) => (b.rsi14 ?? 0) - (a.rsi14 ?? 0));
    const high = ranked[0];
    const low = ranked[ranked.length - 1];
    if (high.ticker !== low.ticker) {
      insights.push({
        id: "rsi",
        text: `${high.ticker} has the highest RSI (${high.rsi14?.toFixed(1)}); ${low.ticker} has the lowest (${low.rsi14?.toFixed(1)}).`,
      });
    }
  }

  const withSentiment = rows.filter((row) => row.sentiment7d !== null);
  if (withSentiment.length > 1) {
    const ranked = [...withSentiment].sort((a, b) => (b.sentiment7d ?? 0) - (a.sentiment7d ?? 0));
    const high = ranked[0];
    const low = ranked[ranked.length - 1];
    if (high.ticker !== low.ticker) {
      insights.push({
        id: "sentiment",
        text: `${high.ticker} has the strongest trailing-week sentiment (${formatSignedNumber(high.sentiment7d ?? 0)}); ${low.ticker} has the weakest (${formatSignedNumber(low.sentiment7d ?? 0)}).`,
      });
    }
  }

  const sectors = Array.from(
    new Set(rows.map((row) => row.sector).filter((sector): sector is string => Boolean(sector))),
  );
  if (sectors.length === 1 && rows.every((row) => row.sector === sectors[0])) {
    insights.push({
      id: "sectors",
      text: `All selected names are in ${sectors[0]}.`,
    });
  } else if (sectors.length > 1) {
    insights.push({
      id: "sectors",
      text: `Basket spans ${sectors.length} sectors: ${sectors.join(", ")}.`,
    });
  }

  return insights;
}

export function formatSignedPct(value: number): string {
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}%`;
}

export function formatSignedNumber(value: number, digits = 2): string {
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(digits)}`;
}

function joinTickers(tickers: string[]): string {
  if (tickers.length === 1) return tickers[0];
  if (tickers.length === 2) return `${tickers[0]} and ${tickers[1]}`;
  return `${tickers.slice(0, -1).join(", ")}, and ${tickers[tickers.length - 1]}`;
}
