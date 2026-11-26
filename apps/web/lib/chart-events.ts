/**
 * Chart events (A3.5, M2.8): news, earnings, ex-dividend dates, splits and
 * the viewer's own fills as markers on the price pane.
 *
 * URL state: `?events=news,split` lists the types shown; absent means the
 * default (news, earnings, dividends, splits, and fills when signed in);
 * `?events=` (empty) shows none. Links leave it out at the default.
 *
 * Placement, the drawings' anchor rule (`lib/drawings/anchor.ts`): on weekly
 * and monthly bars an event sits on the bar whose ISO week or calendar month
 * contains its date. On daily bars it sits on its own date's bar, else the
 * first bar after it (a Saturday headline shows on Monday, the first session
 * that could react). An event after the last loaded bar has no marker but
 * stays in the "Chart events" list.
 */

import type { components } from "@/lib/api/schema";
import { anchorBar, barDate } from "@/lib/drawings/anchor";
import type { StockInterval } from "@/lib/stock-workspace";

export type NewsEvent = components["schemas"]["NewsEventOut"];
export type EarningsEvent = components["schemas"]["EarningsMarkerOut"];
export type DividendEvent = components["schemas"]["DividendEventOut"];
export type SplitEvent = components["schemas"]["SplitEventOut"];
export type FillEvent = components["schemas"]["FillEventOut"];
export type ChartEvent = NewsEvent | EarningsEvent | DividendEvent | SplitEvent | FillEvent;
export type SymbolEvents = components["schemas"]["SymbolEventsOut"];

export const EVENT_TYPES = ["news", "earnings", "dividend", "split", "fill"] as const;
export type EventType = (typeof EVENT_TYPES)[number];

export const EVENT_LABELS: Record<EventType, string> = {
  news: "News",
  earnings: "Earnings",
  dividend: "Dividends",
  split: "Splits",
  fill: "My fills",
};

/** One letter on the marker; the colour and the list carry the rest. */
export const EVENT_LETTER: Record<EventType, string> = {
  news: "N",
  earnings: "E",
  dividend: "D",
  split: "S",
  fill: "",
};

export function defaultEventTypes(signedIn: boolean): EventType[] {
  return signedIn ? [...EVENT_TYPES] : ["news", "earnings", "dividend", "split"];
}

/** `?events=` -> a normalised list in canonical order, or undefined (the default). */
export function parseEventsParam(raw: string | string[] | undefined): string | undefined {
  if (raw === undefined) return undefined;
  const text = Array.isArray(raw) ? raw.join(",") : raw;
  const wanted = new Set(text.split(",").map((t) => t.trim().toLowerCase()));
  return EVENT_TYPES.filter((t) => wanted.has(t)).join(",");
}

/** The types shown for a URL value and a viewer. Fills only for a signed-in viewer. */
export function resolveEventTypes(param: string | undefined, signedIn: boolean): EventType[] {
  if (param === undefined) return defaultEventTypes(signedIn);
  const wanted = new Set(param.split(",").filter(Boolean));
  return EVENT_TYPES.filter((t) => wanted.has(t) && (t !== "fill" || signedIn));
}

/** The URL value after toggling one type; undefined when that is the default again. */
export function toggleEventsParam(
  param: string | undefined,
  type: EventType,
  signedIn: boolean,
): string | undefined {
  const current = new Set(resolveEventTypes(param, signedIn));
  if (current.has(type)) current.delete(type);
  else current.add(type);
  const next = EVENT_TYPES.filter((t) => current.has(t));
  const defaults = defaultEventTypes(signedIn);
  if (next.length === defaults.length && next.every((t, i) => t === defaults[i])) return undefined;
  return next.join(",");
}

/** The bar an event's date sits on, or null (after the last bar, or no bar in its period). */
export function eventBarIndex(
  date: string,
  interval: StockInterval,
  barDates: readonly string[],
): number | null {
  if (interval !== "1d") return anchorBar(date, interval, barDates)?.index ?? null;
  // Daily: the bar on the date, else the first one after it.
  let lo = 0;
  let hi = barDates.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (barDates[mid] < date) lo = mid + 1;
    else hi = mid;
  }
  return lo < barDates.length ? lo : null;
}

/** Events per bar index, in their list order. */
export function eventsByBar(
  events: readonly ChartEvent[],
  interval: StockInterval,
  barTimes: readonly string[],
): Map<number, ChartEvent[]> {
  const dates = barTimes.map(barDate);
  const out = new Map<number, ChartEvent[]>();
  for (const event of events) {
    const index = eventBarIndex(event.date, interval, dates);
    if (index === null) continue;
    const list = out.get(index) ?? [];
    list.push(event);
    out.set(index, list);
  }
  return out;
}

const NUMBER = new Intl.NumberFormat("en-US", { maximumFractionDigits: 6 });

function ratio(value: string): string {
  return NUMBER.format(Number(value));
}

/** "4-for-1 split", "1-for-10 reverse split". */
export function splitLabel(event: SplitEvent): string {
  const from = Number(event.ratio_from);
  const to = Number(event.ratio_to);
  return `${ratio(event.ratio_to)}-for-${ratio(event.ratio_from)} ${to < from ? "reverse split" : "split"}`;
}

/** One line per event, for the list, the legend and the canvas's text summary. */
export function eventSummary(event: ChartEvent, currency?: string): string {
  switch (event.type) {
    case "news":
      return `${event.count} news ${event.count === 1 ? "item" : "items"}${
        event.sources.length ? ` (${event.sources.join(", ")})` : ""
      }`;
    case "earnings": {
      const parts = [event.fiscal_period, event.report_time].filter(Boolean).join(", ");
      const eps =
        event.eps_actual !== null && event.eps_actual !== undefined
          ? `; EPS ${NUMBER.format(Number(event.eps_actual))}${
              event.eps_estimate !== null && event.eps_estimate !== undefined
                ? ` vs ${NUMBER.format(Number(event.eps_estimate))} estimated`
                : ""
            }`
          : "";
      return `Earnings${parts ? ` (${parts})` : ""}${eps}`;
    }
    case "dividend":
      return `Ex-dividend ${NUMBER.format(Number(event.amount))} ${event.currency || currency || ""}`.trim();
    case "split":
      return splitLabel(event);
    case "fill": {
      const base = `${event.side === "sell" ? "Sold" : "Bought"} ${NUMBER.format(Number(event.quantity))} at ${NUMBER.format(Number(event.price))}`;
      // A5.5: the fill that closes a journal entry carries the entry's R.
      return event.r_multiple !== null && event.r_multiple !== undefined
        ? `${base}, closing the trade at ${formatR(event.r_multiple)}`
        : base;
    }
  }
}

/** A short count for the legend: "2 news, earnings". */
export function legendEvents(events: readonly ChartEvent[]): string {
  const parts: string[] = [];
  const news = events
    .filter((e) => e.type === "news")
    .reduce((n, e) => n + (e as NewsEvent).count, 0);
  if (news) parts.push(`${news} news`);
  for (const type of ["earnings", "dividend", "split"] as const) {
    if (events.some((e) => e.type === type)) {
      parts.push(type === "dividend" ? "ex-dividend" : type);
    }
  }
  const fills = events.filter((e) => e.type === "fill").length;
  if (fills) parts.push(`${fills} ${fills === 1 ? "fill" : "fills"}`);
  return parts.join(", ");
}

/** The merged list, filtered to the shown types, oldest first, fills by time. */
export function mergeEvents(
  lists: readonly (readonly ChartEvent[] | null | undefined)[],
  types: readonly EventType[],
): ChartEvent[] {
  const wanted = new Set(types);
  const order = new Map(EVENT_TYPES.map((t, i) => [t, i]));
  return lists
    .flatMap((list) => list ?? [])
    .filter((e) => wanted.has(e.type))
    .sort(
      (a, b) =>
        a.date.localeCompare(b.date) ||
        (order.get(a.type) ?? 0) - (order.get(b.type) ?? 0) ||
        ("ts" in a && "ts" in b ? a.ts.localeCompare(b.ts) : 0),
    );
}

/** A stable key for an event in lists. */
export function eventKey(event: ChartEvent, index: number): string {
  return `${event.type}-${event.date}-${"ts" in event ? event.ts : index}`;
}

/** An R multiple as the journal writes it: "+1.25R", "-0.40R". */
export function formatR(value: number): string {
  const sign = value > 0 ? "+" : value < 0 ? "-" : "";
  return `${sign}${Math.abs(value).toFixed(2)}R`;
}
