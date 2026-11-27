/** A7.11 (M10.6): the optimiser's URL state and request (pure, for tests). */

import type { components } from "./api/schema";

export type OptimiseRequest = components["schemas"]["OptimiseIn"];
export type OptimiseResult = components["schemas"]["OptimiseOut"];
export type OptimiseMethod = OptimiseRequest["method"];

export const OPTIMISE_METHODS: {
  value: NonNullable<OptimiseMethod>;
  label: string;
  note: string;
}[] = [
  {
    value: "hrp",
    label: "Hierarchical Risk Parity",
    note: "Clusters by correlation; no return forecasts.",
  },
  {
    value: "min_volatility",
    label: "Minimum Volatility",
    note: "Lowest variance on the shrunk covariance.",
  },
  { value: "max_sharpe", label: "Maximum Sharpe", note: "Leans on noisy historical mean returns." },
  { value: "min_cvar", label: "Minimum CVaR", note: "Smallest average loss in the worst days." },
  {
    value: "black_litterman",
    label: "Black-Litterman",
    note: "Market-cap prior plus your views, then max Sharpe.",
  },
];

export type OptimiseParams = {
  tickers?: string;
  method?: string;
  years?: string;
  rf?: string;
  maxw?: string;
  cash?: string;
  views?: string;
};

function num(raw: string | undefined, lo: number, hi: number, fallback: number): number {
  const n = Number(raw);
  return Number.isFinite(n) && raw !== undefined && raw !== ""
    ? Math.min(hi, Math.max(lo, n))
    : fallback;
}

/** "WILD 30% 0.8, KO 6 0.5": ticker, expected annual return (percent), confidence 0-1. */
export function parseViews(raw: string | undefined): OptimiseRequest["views"] {
  if (!raw) return [];
  return raw
    .split(/[,\n;]+/)
    .map((part) => part.trim().split(/\s+/))
    .filter((p) => p.length === 3)
    .map(([ticker, ret, conf]) => ({
      ticker: ticker.toUpperCase(),
      expected_return: Number(ret.replace("%", "")) / 100,
      confidence: Number(conf),
    }))
    .filter(
      (v) =>
        Number.isFinite(v.expected_return) &&
        Number.isFinite(v.confidence) &&
        v.confidence > 0 &&
        v.confidence <= 1,
    )
    .slice(0, 30);
}

export function parseTickers(raw: string | undefined): string[] {
  const seen = new Set<string>();
  for (const t of (raw ?? "").split(/[\s,]+/)) {
    const v = t.trim().toUpperCase();
    if (v) seen.add(v.slice(0, 16));
  }
  return [...seen].slice(0, 30);
}

export function optimiseRequest(p: OptimiseParams): OptimiseRequest | null {
  const tickers = parseTickers(p.tickers);
  if (tickers.length < 2) return null;
  const method = OPTIMISE_METHODS.some((m) => m.value === p.method)
    ? (p.method as OptimiseMethod)
    : "hrp";
  const cash = num(p.cash, 0, 1e12, 0);
  return {
    tickers,
    method,
    years: Math.round(num(p.years, 1, 10, 3)),
    risk_free_rate: num(p.rf, 0, 20, 4) / 100,
    max_weight: num(p.maxw, 1, 100, 100) / 100,
    beta: 0.95,
    delta: 2.5,
    cash: cash > 0 ? cash : null,
    views: method === "black_litterman" ? parseViews(p.views) : [],
  };
}

export function pct(value: number | null | undefined, digits = 1): string {
  return value == null ? "—" : `${(value * 100).toFixed(digits)}%`;
}

/** The API's `detail` from an `ApiError` message ("API 400 /path: {...}"), else null. */
export function errorDetail(message: string): string | null {
  const i = message.indexOf(": ");
  if (i < 0) return null;
  try {
    const body = JSON.parse(message.slice(i + 2)) as { detail?: unknown };
    return typeof body.detail === "string" ? body.detail : null;
  } catch {
    return null;
  }
}
