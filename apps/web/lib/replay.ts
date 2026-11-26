import { parseApiTimestamp } from "@/lib/api-time";
import type { Bar } from "@/lib/api/types";

export const REPLAY_PROFILE_LABEL = "legacy_close v1";

/** A6.9: the replay profiles (the API's `REPLAY_PROFILES`), default first. */
export const REPLAY_PROFILES = [
  {
    value: "legacy_close",
    version: "v1",
    label: "Close only",
    description: "Resting orders trigger on each later close and fill at it.",
  },
  {
    value: "intrabar_ohlc",
    version: "v1",
    label: "Bar range",
    description:
      "Resting orders are judged on each bar's open, high and low, the open first. A stop and a target inside one bar: the stored minutes decide, else the stop fills first.",
  },
] as const;

export type ReplayProfileValue = (typeof REPLAY_PROFILES)[number]["value"];

/** "intrabar_ohlc v1": the name the session page shows. */
export function replayProfileLabel(name?: string | null, version?: string | null): string {
  if (!name) return REPLAY_PROFILE_LABEL;
  return `${name} ${version ?? "v1"}`;
}

/** A6.9: the bar intervals a session can run on. */
export const REPLAY_INTERVALS = [
  { value: "1d", label: "Daily" },
  { value: "1m", label: "1 minute" },
  { value: "5m", label: "5 minutes" },
  { value: "15m", label: "15 minutes" },
  { value: "60m", label: "60 minutes" },
] as const;

export type ReplayIntervalValue = (typeof REPLAY_INTERVALS)[number]["value"];

export function replayIntervalLabel(value?: string | null): string {
  return REPLAY_INTERVALS.find((i) => i.value === (value ?? "1d"))?.label ?? value ?? "Daily";
}

export function isIntradayInterval(value?: string | null): boolean {
  return !!value && value !== "1d";
}

/** A6.9: autoplay speeds, in bars a second. */
export const AUTOPLAY_SPEEDS = [1, 2, 5, 10] as const;
export type AutoplaySpeed = (typeof AUTOPLAY_SPEEDS)[number];

/** The time between the starts of two steps at `speed` bars a second. */
export function autoplayDelayMs(speed: AutoplaySpeed): number {
  return Math.round(1000 / speed);
}

/** Number keys 1-4 pick the speeds 1, 2, 5 and 10 bars a second. */
export function speedForKey(key: string): AutoplaySpeed | null {
  const index = ["1", "2", "3", "4"].indexOf(key);
  return index >= 0 ? AUTOPLAY_SPEEDS[index] : null;
}

/** The next speed up (`+1`) or down (`-1`), clamped. */
export function stepSpeed(speed: AutoplaySpeed, direction: 1 | -1): AutoplaySpeed {
  const index = AUTOPLAY_SPEEDS.indexOf(speed);
  const next = Math.max(0, Math.min(AUTOPLAY_SPEEDS.length - 1, index + direction));
  return AUTOPLAY_SPEEDS[next];
}
export const REPLAY_DEFAULT_CASH = "100000";
export const REPLAY_CASH_PRESETS = ["25000", "50000", "100000", "250000"] as const;
/** A4.6: rupee sessions start at ₹10 lakh by default (API `default_starting_cash`). */
export const REPLAY_CASH_PRESETS_BY_CURRENCY: Record<string, readonly string[]> = {
  USD: REPLAY_CASH_PRESETS,
  INR: ["250000", "500000", "1000000", "2500000"],
};

export function replayCashPresets(currency: string): readonly string[] {
  return REPLAY_CASH_PRESETS_BY_CURRENCY[currency] ?? REPLAY_CASH_PRESETS;
}

export const REPLAY_ORDER_TYPES = [
  { value: "market", label: "Market" },
  { value: "limit", label: "Limit" },
  { value: "stop_loss", label: "Stop-loss" },
  { value: "take_profit", label: "Take-profit" },
  { value: "bracket", label: "Bracket" },
] as const;

export type ReplayTicketOrderType = (typeof REPLAY_ORDER_TYPES)[number]["value"];

export function replayOrderTypeLabel(value: string): string {
  return REPLAY_ORDER_TYPES.find((t) => t.value === value)?.label ?? value;
}

export function isoDate(iso: string): string {
  return iso.slice(0, 10);
}

export function toReplayTimestamp(date: string): string {
  return `${date}T00:00:00.000Z`;
}

export function formatReplayDate(iso: string): string {
  return parseApiTimestamp(iso).toLocaleDateString("en-US", {
    weekday: "long",
    month: "long",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  });
}

export function formatReplayShortDate(iso: string): string {
  return parseApiTimestamp(iso).toLocaleDateString("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  });
}

/** A6.9: the replay clock: the date of a daily bar, the date and UTC time of an intraday one. */
export function formatReplayClock(iso: string, interval?: string | null): string {
  if (!isIntradayInterval(interval)) return formatReplayDate(iso);
  const at = parseApiTimestamp(iso);
  const day = at.toLocaleDateString("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  });
  const time = at.toLocaleTimeString("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "UTC",
  });
  return `${day}, ${time} UTC`;
}

export function formatReplayDay(iso: string): string {
  return parseApiTimestamp(iso).toLocaleDateString("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
}

export function replayProgressPct(
  startAt: string,
  currentAt: string,
  endAt: string,
  status: string,
): number {
  if (status === "completed" || currentAt >= endAt) return 100;
  const start = Date.parse(startAt);
  const current = Date.parse(currentAt);
  const end = Date.parse(endAt);
  if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) return 0;
  return Math.max(0, Math.min(100, Math.round(((current - start) / (end - start)) * 100)));
}

export function replayBarsToChart(
  bars: Array<{
    ts: string;
    open: string;
    high: string;
    low: string;
    close: string;
    volume: number;
  }>,
): Bar[] {
  return bars.map((bar) => ({
    ts: bar.ts,
    open: bar.open,
    high: bar.high,
    low: bar.low,
    close: bar.close,
    volume: bar.volume,
  }));
}

export function replayStatusLabel(status: string): string {
  if (status === "completed") return "Completed";
  if (status === "cancelled") return "Cancelled";
  return "Active";
}

export function replayErrorMessage(status: number, detail?: string): string {
  if (status === 404) return "That replay session was not found.";
  if (status === 409 && detail?.toLowerCase().includes("locked")) {
    return "Thesis fields are locked after the first fill. You can still update reflection.";
  }
  if (status === 409) return "This replay is no longer active.";
  // A4.6: the 30-day lag, an index session and an order the API refuses say why.
  if (
    status === 400 &&
    detail &&
    /days before today|index|order|price|sell-only|bracket|stop|target|minute|interval/i.test(
      detail,
    )
  ) {
    return detail;
  }
  // A6.9: autoplay went faster than the per-user advance limit.
  if (status === 429) return "Too many steps at once: wait a moment and step again.";
  if (status === 400) return "That historical range has no stored daily bars.";
  if (status === 422) return "Not enough replay cash or shares for that order.";
  if (status === 401) return "Sign in to use Replay Lab.";
  return "Something went wrong with this replay.";
}

export function replayFillMarkers(fills: Array<{ side: string; evaluated_at: string }>): Array<{
  time: string;
  position: "aboveBar" | "belowBar";
  color: string;
  shape: "arrowUp" | "arrowDown";
  text: string;
}> {
  return fills.map((fill) =>
    fill.side.toLowerCase() === "buy"
      ? {
          time: fill.evaluated_at,
          position: "belowBar" as const,
          color: "rgb(34 197 94)",
          shape: "arrowUp" as const,
          text: "BUY",
        }
      : {
          time: fill.evaluated_at,
          position: "aboveBar" as const,
          color: "rgb(239 68 68)",
          shape: "arrowDown" as const,
          text: "SELL",
        },
  );
}

export function datesDiffer(requested: string | undefined, resolvedIso: string): boolean {
  if (!requested) return false;
  return isoDate(requested) !== isoDate(resolvedIso);
}

/** A6.9: the order list's rows: plain orders, and brackets as one linked group. */
export type ReplayOrderRow<O> =
  | { kind: "single"; order: O }
  | { kind: "bracket"; entry: O; stop: O | null; target: O | null };

/** Newest first; a bracket's entry, stop and target are one row. */
export function groupReplayOrders<
  O extends { id: number; order_type: string; parent_id?: number | null },
>(orders: readonly O[]): ReplayOrderRow<O>[] {
  const children = new Map<number, O[]>();
  for (const order of orders) {
    if (order.parent_id != null) {
      const list = children.get(order.parent_id) ?? [];
      list.push(order);
      children.set(order.parent_id, list);
    }
  }
  const rows: ReplayOrderRow<O>[] = [];
  for (const order of [...orders].reverse()) {
    if (order.parent_id != null && orders.some((o) => o.id === order.parent_id)) continue;
    if (order.order_type === "bracket") {
      const kids = children.get(order.id) ?? [];
      rows.push({
        kind: "bracket",
        entry: order,
        stop: kids.find((k) => k.order_type === "stop_loss") ?? null,
        target: kids.find((k) => k.order_type === "take_profit") ?? null,
      });
    } else {
      rows.push({ kind: "single", order });
    }
  }
  return rows;
}
