/**
 * A6.5: closed minute bars from the stream worker, merged into an intraday
 * chart's bars as they are stored (`GET /v1/stream/bars`, server-sent events).
 *
 * Each event is one stored 1-minute bar (ticker, feed, `ts` = its open,
 * `closed_at`, OHLCV as strings). On a 1-minute chart it is the next bar (or
 * the newest one again). On 5, 15, 30 or 60 minutes it joins the newest bar
 * while it falls inside it, or opens the next bucket: buckets step from the
 * newest bar's close within a session (the server aligns them to the
 * session's open), and a minute after a long gap opens a new session's first
 * bar at its own time. The merged bar stays `partial` until its close; a
 * reload gives the server's exact view.
 *
 * Only the chart's own feed is merged (an `iex` chart ignores `replayed`
 * bars). A minute the newest bar already holds (its `minutes` count covers
 * it) is not counted twice.
 */

import type { Bar } from "@/lib/api/types";

export type LiveBarEvent = {
  ticker: string;
  feed: string;
  badge: string;
  interval: string;
  ts: string;
  closed_at: string;
  open: string;
  high: string;
  low: string;
  close: string;
  volume: number;
  replayed: boolean;
};

const MINUTE_MS = 60_000;
/** A gap longer than this between minutes is a new session (or a pause). */
const SESSION_GAP_MS = 60 * MINUTE_MS;

export const INTERVAL_MINUTES: Record<string, number> = {
  "1m": 1,
  "5m": 5,
  "15m": 15,
  "30m": 30,
  "60m": 60,
};

export function parseLiveBar(raw: string): LiveBarEvent | null {
  try {
    const v = JSON.parse(raw) as Partial<LiveBarEvent>;
    if (
      typeof v.ticker !== "string" ||
      typeof v.feed !== "string" ||
      typeof v.ts !== "string" ||
      typeof v.closed_at !== "string" ||
      typeof v.close !== "string" ||
      Number.isNaN(Date.parse(v.ts))
    ) {
      return null;
    }
    return v as LiveBarEvent;
  } catch {
    return null;
  }
}

function iso(ms: number): string {
  return new Date(ms).toISOString().replace(".000Z", "Z");
}

/** The venue's date of an instant (`YYYY-MM-DD`), for session breaks. */
export function venueDate(ms: number, timeZone: string): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date(ms));
}

function num(value: string): number {
  return Number.parseFloat(value);
}

function maxStr(a: string, b: string): string {
  return num(b) > num(a) ? b : a;
}

function minStr(a: string, b: string): string {
  return num(b) < num(a) ? b : a;
}

/**
 * The chart's bars with one stored minute merged in, or the same array when
 * the minute is not this chart's (another feed, already held, older).
 * The length is kept: a new bar drops the oldest.
 */
export function mergeLiveBar(
  bars: Bar[],
  event: LiveBarEvent,
  interval: string,
  timeZone = "UTC",
): Bar[] {
  const n = INTERVAL_MINUTES[interval];
  const last = bars.at(-1);
  if (!n || !last || event.interval !== "1m") return bars;
  if ((last.feed ?? null) !== event.feed) return bars;
  const evTs = Date.parse(event.ts);
  const lastTs = Date.parse(last.ts);
  if (Number.isNaN(evTs) || Number.isNaN(lastTs) || evTs < lastTs) return bars;
  const lastClose = last.closed_at ? Date.parse(last.closed_at) : lastTs + n * MINUTE_MS;
  const base = {
    source: null,
    feed: event.feed,
    badge: event.badge,
  } satisfies Partial<Bar>;

  if (n === 1) {
    const bar: Bar = {
      ...base,
      ts: iso(evTs),
      closed_at: event.closed_at,
      session_date: venueDate(evTs, timeZone),
      open: event.open,
      high: event.high,
      low: event.low,
      close: event.close,
      volume: event.volume,
      minutes: 1,
      partial: false,
    };
    if (evTs === lastTs) return [...bars.slice(0, -1), bar];
    return [...bars.slice(1), bar];
  }

  if (evTs < lastClose) {
    const held = lastTs + (last.minutes ?? 0) * MINUTE_MS;
    if (evTs < held) return bars; // the server's bar already has this minute
    const evClose = Date.parse(event.closed_at);
    const merged: Bar = {
      ...last,
      high: maxStr(last.high, event.high),
      low: minStr(last.low, event.low),
      close: event.close,
      volume: last.volume + event.volume,
      minutes: (last.minutes ?? 0) + 1,
      partial: evClose < lastClose,
    };
    return [...bars.slice(0, -1), merged];
  }

  const step = n * MINUTE_MS;
  const start =
    evTs - lastClose < SESSION_GAP_MS
      ? lastClose + Math.floor((evTs - lastClose) / step) * step
      : evTs;
  const close = start + step;
  const bar: Bar = {
    ...base,
    ts: iso(start),
    closed_at: iso(close),
    session_date: venueDate(start, timeZone),
    open: event.open,
    high: event.high,
    low: event.low,
    close: event.close,
    volume: event.volume,
    minutes: 1,
    partial: Date.parse(event.closed_at) < close,
  };
  return [...bars.slice(1), bar];
}

export function liveStreamUrl(base: string, ticker: string): string {
  return `${base.replace(/\/$/, "")}/v1/stream/bars?tickers=${encodeURIComponent(ticker)}`;
}

export type LiveStatus = "connecting" | "waiting" | "live" | "offline";

/** The status line under an intraday chart's source badge. */
export function liveStatusText(
  status: LiveStatus,
  lastAt: string | null,
  replayed: boolean,
  timeZone: string,
): string {
  if (status === "offline") return "Live updates offline: the stream can't be reached.";
  if (status === "connecting") return "Connecting to live updates…";
  if (status === "waiting" || !lastAt) {
    return "Live updates on: new bars appear here as the stream stores them.";
  }
  const time = new Intl.DateTimeFormat("en-GB", {
    timeZone,
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(lastAt));
  return replayed ? `Replayed stream, not live: last bar ${time}.` : `Live: last bar ${time}.`;
}
