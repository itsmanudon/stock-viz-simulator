import { apiTimestampMs, barTimeToUtcSeconds } from "@/lib/api-time";
import type { Bar, IndicatorPoint, MACDPoint } from "@/lib/api/types";
import { type ChartView, DEFAULT_CHART_VIEW, setChartViewParams } from "@/lib/chart-view";

const QUANTITY_SCALE = 1_000_000;

export const STOCK_TIMEFRAMES = ["1M", "3M", "6M", "1Y", "5Y", "MAX"] as const;

/**
 * A1.4a: the bar interval, separate from the lookback range above. Weekly and
 * monthly bars are resampled by the API from the daily ones; the newest can
 * be `partial` (its week or month is not over).
 */
export const STOCK_INTERVALS = [
  { value: "1d", label: "Daily", short: "D" },
  { value: "1wk", label: "Weekly", short: "W" },
  { value: "1mo", label: "Monthly", short: "M" },
] as const;

/**
 * A6.2: intraday intervals, offered only when the symbol has intraday bars
 * (`symbol.intraday.intervals`). `60m` is the API's name; the button reads 1h.
 */
export const INTRADAY_INTERVALS = [
  { value: "1m", label: "1m", short: "1m", minutes: 1 },
  { value: "5m", label: "5m", short: "5m", minutes: 5 },
  { value: "15m", label: "15m", short: "15m", minutes: 15 },
  { value: "30m", label: "30m", short: "30m", minutes: 30 },
  { value: "60m", label: "1h", short: "1h", minutes: 60 },
] as const;

export type DailyInterval = (typeof STOCK_INTERVALS)[number]["value"];
export type IntradayInterval = (typeof INTRADAY_INTERVALS)[number]["value"];
export type StockInterval = DailyInterval | IntradayInterval;

export function isIntradayInterval(interval: string | undefined): interval is IntradayInterval {
  return INTRADAY_INTERVALS.some((i) => i.value === interval);
}

export function parseStockInterval(raw: string | undefined): StockInterval {
  if (isIntradayInterval(raw)) return raw;
  return STOCK_INTERVALS.some((i) => i.value === raw) ? (raw as StockInterval) : "1d";
}

/** Trading days a lookback covers, as bars of `interval` (weeks of five, months of 21). */
export function barsForLookback(days: number, interval: StockInterval): number {
  if (interval === "1wk") return Math.min(5000, Math.ceil(days / 5));
  if (interval === "1mo") return Math.min(5000, Math.ceil(days / 21));
  return days;
}

/**
 * A6.2: intraday lookbacks, in sessions. Each interval offers the ranges that
 * fit the bars route's 5,000-bar cap at that interval (1 minute: a day or a
 * week; 1 hour: up to a year).
 */
export const INTRADAY_LOOKBACKS = [
  { value: "1D", sessions: 1 },
  { value: "5D", sessions: 5 },
  { value: "1M", sessions: 22 },
  { value: "3M", sessions: 65 },
  { value: "1Y", sessions: 252 },
] as const;
export type IntradayLookback = (typeof INTRADAY_LOOKBACKS)[number]["value"];

const LOOKBACKS_BY_INTERVAL: Record<IntradayInterval, readonly IntradayLookback[]> = {
  "1m": ["1D", "5D"],
  "5m": ["1D", "5D", "1M"],
  "15m": ["5D", "1M", "3M"],
  "30m": ["5D", "1M", "3M"],
  "60m": ["1M", "3M", "1Y"],
};
const DEFAULT_LOOKBACK: Record<IntradayInterval, IntradayLookback> = {
  "1m": "1D",
  "5m": "5D",
  "15m": "5D",
  "30m": "1M",
  "60m": "1M",
};

/** The lookbacks an intraday interval offers, oldest-reaching last. */
export function intradayLookbacks(interval: IntradayInterval): readonly IntradayLookback[] {
  return LOOKBACKS_BY_INTERVAL[interval];
}

/** The URL's lookback if this interval offers it, else the interval's default. */
export function parseIntradayLookback(
  raw: string | undefined,
  interval: IntradayInterval,
): IntradayLookback {
  return LOOKBACKS_BY_INTERVAL[interval].includes(raw as IntradayLookback)
    ? (raw as IntradayLookback)
    : DEFAULT_LOOKBACK[interval];
}

/** Minutes in a regular session: NSE/BSE 09:15-15:30, else New York 09:30-16:00. */
export function sessionMinutes(indian: boolean): number {
  return indian ? 375 : 390;
}

/**
 * Bars an intraday lookback asks for: (sessions + 1) x bars a regular session
 * holds at the interval (the last one of a session is clipped, so it rounds
 * up), capped at the route's 5,000. "1D" on 1 minute asks for 750 bars on
 * NSE (2 x 375) and keeps the last session; "1M" on 1 hour 23 x 7 = 161.
 */
export function intradayBarsForLookback(
  lookback: IntradayLookback,
  interval: IntradayInterval,
  indian: boolean,
): number {
  const spec = INTRADAY_LOOKBACKS.find((l) => l.value === lookback) ?? INTRADAY_LOOKBACKS[0];
  const minutes = INTRADAY_INTERVALS.find((i) => i.value === interval)?.minutes ?? 1;
  const perSession = Math.ceil(sessionMinutes(indian) / minutes);
  // One session of headroom: the page keeps the newest whole sessions
  // (`lastSessions`), so a short session never leaves the window a day short.
  return Math.min(5000, (spec.sessions + 1) * perSession);
}

/** Sessions an intraday lookback covers. */
export function sessionsForLookback(lookback: IntradayLookback): number {
  return INTRADAY_LOOKBACKS.find((l) => l.value === lookback)?.sessions ?? 1;
}

/**
 * The bars of the newest `sessions` sessions (by `session_date`), oldest
 * first. The API's limit counts bars of regular sessions, so a short session
 * (a Muhurat evening, a half day) would otherwise pull in the day before.
 */
export function lastSessions<T extends { ts: string; session_date?: string | null }>(
  bars: readonly T[],
  sessions: number,
): T[] {
  const seen: string[] = [];
  let start = bars.length;
  for (let i = bars.length - 1; i >= 0; i--) {
    const day = bars[i].session_date ?? bars[i].ts.slice(0, 10);
    if (seen.at(-1) !== day) {
      if (seen.length === sessions) break;
      seen.push(day);
    }
    start = i;
  }
  return bars.slice(start);
}

/**
 * An indicator bundle without the points before `ts` (the first bar drawn),
 * so a study never widens the time axis past the bars. Timestamps compare as
 * the API writes them (same ISO form).
 */
export function clipBundleFrom<
  B extends { series: Record<string, IndicatorPoint[]>; macd?: MACDPoint[] | null },
>(bundle: B, ts: string): B {
  const cut = barTimeToUtcSeconds(ts);
  const keep = (p: { ts: string }) => barTimeToUtcSeconds(p.ts) >= cut;
  return {
    ...bundle,
    series: Object.fromEntries(
      Object.entries(bundle.series).map(([key, points]) => [key, points.filter(keep)]),
    ),
    macd: bundle.macd ? bundle.macd.filter(keep) : bundle.macd,
  };
}

/** "15-minute", "1-hour": an intraday interval in words. */
export function intradayWords(interval: IntradayInterval): string {
  return interval === "60m" ? "1-hour" : `${interval.replace("m", "")}-minute`;
}

/** The caption under a chart whose newest bar is partial, or null. */
export function partialBarLabel(
  bar: { ts: string; partial?: boolean | null } | undefined,
  interval: StockInterval,
  timeZone?: string,
): string | null {
  if (!bar?.partial || interval === "1d") return null;
  if (isIntradayInterval(interval)) {
    const opened = formatBarTime(bar.ts, timeZone ?? "UTC");
    return `Latest ${intradayWords(interval)} bar so far (partial), opened ${opened}. It is not a closed bar.`;
  }
  const period = interval === "1wk" ? "week" : "month";
  const through = formatCloseDate(bar.ts) ?? bar.ts;
  return `Latest ${period} so far (partial), sessions through ${through}. It is not a closed bar.`;
}

const ZONE_NAMES: Record<string, string> = {
  "Asia/Kolkata": "IST",
  "Asia/Calcutta": "IST",
  UTC: "UTC",
};

/** The short name of a venue's zone: "IST", "ET" (New York), else the IANA name. */
export function zoneLabel(timeZone: string): string {
  if (ZONE_NAMES[timeZone]) return ZONE_NAMES[timeZone];
  if (timeZone === "America/New_York") return "ET";
  return timeZone;
}

const TIME_PARTS = new Map<string, Intl.DateTimeFormat>();

function partsIn(ms: number, timeZone: string) {
  let fmt = TIME_PARTS.get(timeZone);
  if (!fmt) {
    fmt = new Intl.DateTimeFormat("en-US", {
      timeZone,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hourCycle: "h23",
    });
    TIME_PARTS.set(timeZone, fmt);
  }
  const out: Record<string, string> = {};
  for (const part of fmt.formatToParts(new Date(ms))) out[part.type] = part.value;
  return {
    date: `${out.year}-${out.month}-${out.day}`,
    time: `${out.hour}:${out.minute}`,
  };
}

/** An instant (epoch ms) as the venue's "HH:MM". */
export function timeInZone(ms: number, timeZone: string): string {
  return partsIn(ms, timeZone).time;
}

/** An instant (epoch ms) as the venue's calendar date, "YYYY-MM-DD". */
export function dateInZone(ms: number, timeZone: string): string {
  return partsIn(ms, timeZone).date;
}

/**
 * A6.2: an intraday bar's time in its venue's zone with the date and the
 * zone named: "Jan 30, 2026 09:15 IST". API timestamps are naive UTC, read
 * through `apiTimestampMs` (never `new Date(iso)`, audit RS-2).
 */
export function formatBarTime(iso: string, timeZone: string): string {
  const ms = apiTimestampMs(iso);
  if (!Number.isFinite(ms)) return iso;
  const { date, time } = partsIn(ms, timeZone);
  return `${formatCloseDate(date) ?? date} ${time} ${zoneLabel(timeZone)}`;
}

/**
 * A6.2: the source badge the chart shows for an intraday feed: the owner's
 * local files "File · local", the free US feed "IEX only", consolidated
 * "SIP". Null for daily bars.
 */
export function sourceBadgeLabel(feed: string | null | undefined): string | null {
  if (!feed) return null;
  if (feed === "file") return "File · local";
  if (feed === "iex") return "IEX only";
  if (feed === "sip") return "SIP";
  if (feed === "kite") return "Kite";
  return feed;
}

/** What each badge means, for its title and the screen-reader text. */
export function sourceBadgeTitle(feed: string | null | undefined): string {
  if (feed === "file")
    return "Loaded from the owner's local files on this machine; never served in production.";
  if (feed === "iex")
    return "Trades on the IEX exchange only: a small share of all US trading, so volume is partial.";
  if (feed === "sip") return "Consolidated bars from every US exchange (SIP).";
  if (feed === "kite") return "Zerodha Kite Connect bars.";
  return "Intraday bars.";
}
/**
 * The chart's studies (Phase 6.6, A3.4): one entry per study in the API's
 * engine registry (`/v1/indicators/catalog`), with its label, where it draws
 * (`section`, the registry's `pane`), its menu group and how many
 * parameters it takes. `value` is the study with every parameter at its
 * default (the catalog's `default_key`). Parameters, their bounds and the
 * evidence badge come from the catalog; a chart key carries the values
 * (`rsi_21`, `bb_20_2.5`), the API's key grammar.
 */
// biome-ignore format: one study per row reads as a table
export const STOCK_INDICATORS = [
  // --- on the price chart
  { key: "sma", value: "sma_20", label: "SMA", section: "price", group: "trend", params: 1 },
  { key: "ema", value: "ema_20", label: "EMA", section: "price", group: "trend", params: 1 },
  { key: "wma", value: "wma_20", label: "WMA", section: "price", group: "trend", params: 1 },
  { key: "hma", value: "hma_20", label: "Hull MA", section: "price", group: "trend", params: 1 },
  { key: "dema", value: "dema_20", label: "DEMA", section: "price", group: "trend", params: 1 },
  { key: "tema", value: "tema_20", label: "TEMA", section: "price", group: "trend", params: 1 },
  { key: "kama", value: "kama_10_2_30", label: "KAMA", section: "price", group: "trend", params: 3 },
  { key: "vwap", value: "vwap_20", label: "VWAP (rolling)", section: "price", group: "trend", params: 1 },
  { key: "supertrend", value: "supertrend_10_3", label: "Supertrend", section: "price", group: "trend", params: 2 },
  { key: "psar", value: "psar_0.02_0.2", label: "Parabolic SAR", section: "price", group: "trend", params: 2 },
  { key: "ichimoku", value: "ichimoku_9_26_52_26", label: "Ichimoku Cloud", section: "price", group: "trend", params: 4 },
  { key: "pivots", value: "pivots_3", label: "Pivot points (classic)", section: "price", group: "trend", params: 1 },
  { key: "bb", value: "bb_20_2", label: "Bollinger Bands", section: "price", group: "volatility", params: 2 },
  { key: "keltner", value: "keltner_20_2_10", label: "Keltner Channels", section: "price", group: "volatility", params: 3 },
  { key: "donchian", value: "donchian_20", label: "Donchian Channels", section: "price", group: "volatility", params: 1 },
  // --- below the chart
  { key: "rsi", value: "rsi_14", label: "RSI", section: "pane", group: "momentum", params: 1 },
  { key: "macd", value: "macd", label: "MACD", section: "pane", group: "momentum", params: 3 },
  { key: "ppo", value: "ppo_12_26_9", label: "PPO", section: "pane", group: "momentum", params: 3 },
  { key: "stoch", value: "stoch_14_3", label: "Stochastic", section: "pane", group: "momentum", params: 2 },
  { key: "stochrsi", value: "stochrsi_14_14_3_3", label: "Stochastic RSI", section: "pane", group: "momentum", params: 4 },
  { key: "cci", value: "cci_20", label: "CCI", section: "pane", group: "momentum", params: 1 },
  { key: "roc", value: "roc_12", label: "ROC", section: "pane", group: "momentum", params: 1 },
  { key: "willr", value: "willr_14", label: "Williams %R", section: "pane", group: "momentum", params: 1 },
  { key: "tsi", value: "tsi_25_13_7", label: "True Strength Index", section: "pane", group: "momentum", params: 3 },
  { key: "uo", value: "uo_7_14_28", label: "Ultimate Oscillator", section: "pane", group: "momentum", params: 3 },
  { key: "cmo", value: "cmo_9", label: "Chande Momentum", section: "pane", group: "momentum", params: 1 },
  { key: "coppock", value: "coppock_14_11_10", label: "Coppock Curve", section: "pane", group: "momentum", params: 3 },
  { key: "rsline", value: "rsline", label: "RS line (vs index)", section: "pane", group: "momentum", params: 0 },
  { key: "adx", value: "adx_14", label: "ADX", section: "pane", group: "trend", params: 1 },
  { key: "aroon", value: "aroon_25", label: "Aroon", section: "pane", group: "trend", params: 1 },
  { key: "vortex", value: "vortex_14", label: "Vortex", section: "pane", group: "trend", params: 1 },
  { key: "chop", value: "chop_14", label: "Choppiness Index", section: "pane", group: "trend", params: 1 },
  { key: "trix", value: "trix_15", label: "TRIX", section: "pane", group: "trend", params: 1 },
  { key: "elder", value: "elder_13", label: "Elder Ray", section: "pane", group: "trend", params: 1 },
  { key: "atr", value: "atr_14", label: "ATR", section: "pane", group: "volatility", params: 1 },
  { key: "natr", value: "natr_14", label: "ATR %", section: "pane", group: "volatility", params: 1 },
  { key: "hv", value: "hv_20", label: "Historical volatility", section: "pane", group: "volatility", params: 1 },
  { key: "massi", value: "massi_9_25", label: "Mass Index", section: "pane", group: "volatility", params: 2 },
  { key: "rmv", value: "rmv_5_50", label: "RMV tightness", section: "pane", group: "volatility", params: 2 },
  { key: "obv", value: "obv", label: "OBV", section: "pane", group: "volume", params: 0 },
  { key: "ad", value: "ad", label: "Accumulation/Distribution", section: "pane", group: "volume", params: 0 },
  { key: "mfi", value: "mfi_14", label: "MFI", section: "pane", group: "volume", params: 1 },
  { key: "cmf", value: "cmf_20", label: "Chaikin Money Flow", section: "pane", group: "volume", params: 1 },
  { key: "chaikin", value: "chaikin_3_10", label: "Chaikin Oscillator", section: "pane", group: "volume", params: 2 },
  { key: "force", value: "force_13", label: "Force Index", section: "pane", group: "volume", params: 1 },
  { key: "eom", value: "eom_14", label: "Ease of Movement", section: "pane", group: "volume", params: 1 },
  { key: "rvol", value: "rvol_20", label: "Relative volume", section: "pane", group: "volume", params: 1 },
] as const satisfies readonly {
  key: string;
  value: string;
  label: string;
  section: "price" | "pane";
  group: string;
  params: number;
}[];

export type StockStudy = (typeof STOCK_INDICATORS)[number];

/** The API's key grammar: a study name, then each parameter after `_`. */
const KEY_PATTERN = /^([a-z]+)((?:_\d+(?:\.\d+)?)*)$/;

/** `"bb_20_2.5"` -> `{ base: "bb", values: [20, 2.5] }`, or null if it is not a key. */
export function parseIndicatorKey(key: string): { base: string; values: number[] } | null {
  const match = KEY_PATTERN.exec(key.trim().toLowerCase());
  if (!match) return null;
  const values = match[2]
    .split("_")
    .filter(Boolean)
    .map((v) => Number(v));
  return { base: match[1], values };
}

const SERIES_KEY = /^([a-z]+(?:_\d+(?:\.\d+)?)*)(?:\.([a-z_]+))?$/;

/**
 * A series key into its chart key and output: `"bb_20_2.5.upper"` ->
 * `["bb_20_2.5", "upper"]`, `"rsi_14"` -> `["rsi_14", undefined]`. A decimal
 * parameter has a dot too, so never split on the first one.
 */
export function splitSeriesKey(key: string): [string, string | undefined] {
  const match = SERIES_KEY.exec(key);
  return match ? [match[1], match[2]] : [key, undefined];
}

/** The study a key (or a series key like `"bb_20_2.upper"`) belongs to. */
export function studyFor(key: string): StockStudy | undefined {
  const parsed = parseIndicatorKey(splitSeriesKey(key)[0]);
  return parsed ? STOCK_INDICATORS.find((s) => s.key === parsed.base) : undefined;
}

/** `"bb_20_2.5"` -> "Bollinger Bands 20, 2.5"; `"macd"` -> "MACD". Unknown: upper case. */
export function indicatorLabel(key: string): string {
  const parsed = parseIndicatorKey(key);
  const study = parsed ? STOCK_INDICATORS.find((s) => s.key === parsed.base) : undefined;
  if (!parsed || !study) return key.toUpperCase();
  return parsed.values.length ? `${study.label} ${parsed.values.join(", ")}` : study.label;
}

export type ChartPane = {
  name: string;
  label: string;
  lines: Record<string, IndicatorPoint[]>;
  /** A3.5: a legend label per line key, for panes that are not registry studies. */
  outputLabels?: Record<string, string>;
};

/**
 * Split an indicator bundle into price-chart overlays and separate panes by
 * each indicator's registry pane (Phase 6.6). The keys in `own` (the RSI and
 * MACD instances the chart gives their own panes, A3.4) are left out;
 * direction outputs (Supertrend, Parabolic SAR) are states, not lines.
 */
export function chartLayers(
  bundle: {
    series: Record<string, IndicatorPoint[]>;
    meta?: Record<string, { pane: string; label: string }>;
  },
  selected: readonly string[],
  own: readonly (string | undefined)[] = ["rsi_14", "macd"],
): { overlays: Record<string, IndicatorPoint[]>; panes: ChartPane[] } {
  const overlays: Record<string, IndicatorPoint[]> = {};
  const panes: ChartPane[] = [];
  for (const name of selected) {
    if (own.includes(name)) continue;
    const meta = bundle.meta?.[name];
    // By the parsed key, not a prefix: `bb_20_2` must not take `bb_20_2.5.upper`.
    const keys = Object.keys(bundle.series).filter((k) => splitSeriesKey(k)[0] === name);
    if (!keys.length) continue;
    if ((meta?.pane ?? "price") === "price") {
      for (const key of keys) {
        if (!key.endsWith(".direction")) overlays[key] = bundle.series[key];
      }
    } else {
      panes.push({
        name,
        label: indicatorLabel(name),
        lines: Object.fromEntries(
          keys.filter((k) => !k.endsWith(".direction")).map((k) => [k, bundle.series[k]]),
        ),
      });
    }
  }
  return { overlays, panes };
}

/**
 * MACD points for a chart key (A3.4): the API's `macd` field for the default
 * `macd`, else the key's three outputs zipped by date.
 */
export function macdSeries(
  bundle: { series: Record<string, IndicatorPoint[]>; macd?: MACDPoint[] | null },
  key: string,
): MACDPoint[] | null {
  if (key === "macd") return bundle.macd ?? null;
  const line = bundle.series[`${key}.macd`];
  if (!line?.length) return null;
  const signal = new Map((bundle.series[`${key}.signal`] ?? []).map((p) => [p.ts, p.value]));
  const hist = new Map((bundle.series[`${key}.histogram`] ?? []).map((p) => [p.ts, p.value]));
  const out: MACDPoint[] = [];
  for (const p of line) {
    const s = signal.get(p.ts);
    const h = hist.get(p.ts);
    if (s !== undefined && h !== undefined)
      out.push({ ts: p.ts, macd: p.value, signal: s, histogram: h });
  }
  return out;
}

/** A lookback: the daily ranges, or (A6.2) the intraday ones ("1D", "5D"). */
export type StockTimeframe = (typeof STOCK_TIMEFRAMES)[number] | IntradayLookback;
/** A chart key: a study and its parameters (`rsi_21`), A3.4. */
export type StockIndicator = string;

/** Bounds per parameter, from the catalog (A3.4). */
export type ParamBounds = {
  type: "int" | "float";
  min: number;
  max: number;
  min_exclusive: boolean;
  default: number;
};

/** Why `value` is out of bounds for `param`, or null when it is fine. */
export function paramError(param: ParamBounds & { label?: string; name?: string }, value: number) {
  const name = param.label || param.name || "Value";
  if (!Number.isFinite(value)) return `${name} must be a number`;
  if (param.type === "int") {
    if (!Number.isInteger(value) || value < param.min || value > param.max)
      return `${name} must be a whole number from ${param.min} to ${param.max}`;
  } else if (value <= param.min || value > param.max) {
    return `${name} must be above ${param.min} and at most ${param.max}`;
  }
  return null;
}

/** `"bb"`, `[20, 2.5]` -> `"bb_20_2.5"` (no trailing zeros, never exponent form). */
export function buildIndicatorKey(base: string, values: readonly number[]): string {
  const parts = values.map((v) => {
    const text = Number.isInteger(v) ? String(v) : v.toFixed(6).replace(/\.?0+$/, "");
    return text;
  });
  return [base, ...parts].join("_");
}

/**
 * The chart keys in a URL's `indicators` (A3.4). With the catalog's bounds,
 * each key must be a known study with parameters in bounds, and is written
 * in full (`rsi` -> `rsi_14`); without them (the catalog call failed) a key
 * needs a known study and no more parameters than it takes. Duplicates go.
 */
export function parseStockIndicators(
  raw: string | undefined,
  bounds?: Record<string, readonly ParamBounds[]> | null,
): StockIndicator[] {
  if (raw === undefined) return ["sma_50"];
  if (raw === "") return [];
  const out: string[] = [];
  for (const chunk of raw.split(",")) {
    const parsed = parseIndicatorKey(chunk);
    const study = parsed ? STOCK_INDICATORS.find((s) => s.key === parsed.base) : undefined;
    if (!parsed || !study || parsed.values.length > study.params) continue;
    let key = chunk.trim().toLowerCase();
    const params = bounds?.[study.key];
    if (params) {
      if (parsed.values.length > params.length) continue;
      const values = params.map((p, i) => parsed.values[i] ?? p.default);
      if (values.some((v, i) => paramError(params[i], v))) continue;
      key =
        study.key === "macd" && values.every((v, i) => v === params[i].default)
          ? "macd" // the API's original MACD field, which the chart draws
          : buildIndicatorKey(study.key, values);
    }
    if (!out.includes(key)) out.push(key);
  }
  return out;
}

export function buildStockChartHref(
  ticker: string,
  timeframe: StockTimeframe,
  indicators: StockIndicator[],
  interval: StockInterval = "1d",
  view: ChartView = DEFAULT_CHART_VIEW,
): string {
  const params = new URLSearchParams();
  params.set("tf", timeframe);
  params.set("indicators", indicators.join(","));
  // Daily is the default, so its links stay as they were.
  if (interval !== "1d") params.set("interval", interval);
  // A3.1: chart type, scale and adjustment, each left out at its default.
  setChartViewParams(params, view);
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
