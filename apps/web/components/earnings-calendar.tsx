import { ChevronLeft, ChevronRight } from "lucide-react";
import Link from "next/link";

import type { EarningsEvent } from "@/lib/api/types";
import { cn } from "@/lib/utils";

export type EarningsView = "day" | "week" | "month";
export type EarningsScope = "all" | "holdings" | "watchlist";

type CalendarProps = {
  events: EarningsEvent[];
  view: EarningsView;
  scope: EarningsScope;
  anchor: Date;
  /** UTC calendar day to ring as today; defaults to now. */
  today?: string;
};

function dateKey(date: Date): string {
  return date.toISOString().slice(0, 10);
}

function formatDate(value: string): string {
  return new Date(`${value}T12:00:00Z`).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
}

function formatTime(event: EarningsEvent): string {
  if (event.eps_actual !== null && event.eps_estimate !== null) {
    if (event.result === "beat") return "Beat estimate";
    if (event.result === "miss") return "Missed estimate";
    if (event.result === "in_line") return "In line with estimate";
  }
  return event.report_time || "Time not reported";
}

function eventTone(result: EarningsEvent["result"]): string {
  if (result === "beat") return "border-positive/30 bg-positive-soft text-positive";
  if (result === "miss") return "border-negative/30 bg-negative-soft text-negative";
  return "border-border-muted bg-surface-secondary text-text-tertiary";
}

export function EarningsCalendar({
  events,
  view,
  scope,
  anchor,
  today = dateKey(new Date()),
}: CalendarProps) {
  const grouped = new Map<string, EarningsEvent[]>();
  for (const event of events) {
    const list = grouped.get(event.event_date) ?? [];
    list.push(event);
    grouped.set(event.event_date, list);
  }

  const range = viewRange(anchor, view);
  const visibleEvents = events.filter(
    (event) => event.event_date >= range.from && event.event_date <= range.to,
  );
  const href = (next: Record<string, string>) => {
    const query = new URLSearchParams({ view, date: dateKey(anchor), scope, ...next });
    return `/earnings?${query.toString()}`;
  };

  return (
    <>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div
          className="inline-flex gap-0.5 rounded-full border border-border-muted p-0.5"
          aria-label="Calendar view"
        >
          {(["day", "week", "month"] as const).map((option) => (
            <Link
              key={option}
              href={href({ view: option })}
              aria-current={view === option ? "page" : undefined}
              className={cn(
                "rounded-full px-3 py-1.5 text-xs capitalize transition",
                view === option
                  ? "bg-surface-secondary font-medium text-foreground"
                  : "text-text-tertiary hover:bg-surface-hover hover:text-foreground",
              )}
            >
              {option}
            </Link>
          ))}
        </div>
        <div
          className="inline-flex gap-0.5 rounded-full border border-border-muted p-0.5"
          aria-label="Earnings scope"
        >
          {(["all", "holdings", "watchlist"] as const).map((option) => (
            <Link
              key={option}
              href={href({ scope: option })}
              aria-current={scope === option ? "page" : undefined}
              className={cn(
                "rounded-full px-3 py-1.5 text-xs capitalize transition",
                scope === option
                  ? "bg-surface-secondary font-medium text-foreground"
                  : "text-text-tertiary hover:bg-surface-hover hover:text-foreground",
              )}
            >
              {option === "all" ? "All symbols" : option}
            </Link>
          ))}
        </div>
      </div>

      <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Link
            href={href({ date: dateKey(shiftAnchor(anchor, view, -1)) })}
            className="inline-grid size-8 place-items-center rounded-full border border-border-muted text-text-secondary hover:bg-surface-hover hover:text-foreground"
            aria-label="Previous period"
          >
            <ChevronLeft className="size-4" aria-hidden />
          </Link>
          <h2 className="min-w-36 text-center text-sm font-medium">{periodTitle(anchor, view)}</h2>
          <Link
            href={href({ date: dateKey(shiftAnchor(anchor, view, 1)) })}
            className="inline-grid size-8 place-items-center rounded-full border border-border-muted text-text-secondary hover:bg-surface-hover hover:text-foreground"
            aria-label="Next period"
          >
            <ChevronRight className="size-4" aria-hidden />
          </Link>
        </div>
        {/* Explains the result colours, so it shows only when one is on screen. */}
        {visibleEvents.some((event) => event.result !== "unknown") ? <ResultLegend /> : null}
      </div>

      {view === "month" ? (
        <>
          <div className="mt-4 hidden overflow-hidden rounded-xl border border-border-muted lg:block">
            <div className="grid grid-cols-7 border-b border-border-muted text-2xs text-text-tertiary">
              {DAY_NAMES.map((day) => (
                <div key={day} className="px-3 py-2">
                  {day}
                </div>
              ))}
            </div>
            <div className="grid grid-cols-7">
              {monthCells(anchor).map((day) => {
                const key = dateKey(day);
                const dayEvents = grouped.get(key) ?? [];
                // UTC getters throughout: the cells are UTC dates, and local
                // getters shift them a day on a server west of UTC.
                const inMonth = day.getUTCMonth() === anchor.getUTCMonth();
                const weekend = day.getUTCDay() === 0 || day.getUTCDay() === 6;
                const isToday = key === today;
                return (
                  <div
                    key={key}
                    className={cn(
                      "min-h-28 border-r border-b border-border-muted p-2.5 [&:nth-child(7n)]:border-r-0",
                      !inMonth && "bg-surface-secondary/30 text-text-tertiary",
                      inMonth && weekend && "bg-surface-secondary/15",
                    )}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span
                        className={cn(
                          "font-mono text-xs tabular-nums",
                          !inMonth && "opacity-60",
                          isToday && "rounded-full bg-primary px-1.5 text-primary-foreground",
                        )}
                        aria-current={isToday ? "date" : undefined}
                      >
                        {day.getUTCDate()}
                      </span>
                      {dayEvents.length ? (
                        <span className="text-2xs text-text-tertiary">{dayEvents.length}</span>
                      ) : null}
                    </div>
                    <div className="mt-2 space-y-1.5">
                      {dayEvents.map((event) => (
                        <EventRow key={event.id} event={event} compact />
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
          <div className="mt-4 space-y-2 lg:hidden">
            {visibleEvents.length ? (
              visibleEvents.map((event) => <EventRow key={event.id} event={event} />)
            ) : (
              <EmptyCalendarMessage scope={scope} />
            )}
          </div>
        </>
      ) : (
        <div className="mt-4 space-y-2">
          {visibleEvents.length ? (
            visibleEvents.map((event) => <EventRow key={event.id} event={event} />)
          ) : (
            <EmptyCalendarMessage scope={scope} />
          )}
        </div>
      )}
    </>
  );
}

function EventRow({ event, compact = false }: { event: EarningsEvent; compact?: boolean }) {
  return (
    <Link
      href={`/stocks/${event.ticker}`}
      className={cn(
        "block rounded-lg border border-border-muted bg-card transition hover:border-brand/50 hover:bg-surface-hover",
        compact ? "p-2" : "p-3",
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <span className="font-mono text-xs font-semibold">{event.ticker}</span>
        {event.result !== "unknown" ? (
          <span
            className={cn(
              "rounded-full border px-1.5 py-0.5 text-2xs font-medium",
              eventTone(event.result),
            )}
          >
            {event.result === "in_line" ? "In line" : event.result === "beat" ? "Beat" : "Miss"}
          </span>
        ) : null}
      </div>
      <p className={cn("mt-1 truncate text-text-secondary", compact ? "text-2xs" : "text-xs")}>
        {event.name}
      </p>
      <p className="mt-2 text-2xs text-text-tertiary">
        {formatDate(event.event_date)} · {formatTime(event)}
      </p>
    </Link>
  );
}

function ResultLegend() {
  const items = [
    ["Beat estimate", "bg-positive"],
    ["Missed estimate", "bg-negative"],
    ["In line or no result yet", "bg-text-tertiary"],
  ] as const;
  return (
    <ul
      aria-label="Result key"
      className="flex flex-wrap gap-x-4 gap-y-1 text-2xs text-text-secondary"
    >
      {items.map(([label, tone]) => (
        <li key={label} className="inline-flex items-center gap-1.5">
          <span aria-hidden className={cn("h-0.5 w-3.5 rounded-full", tone)} />
          {label}
        </li>
      ))}
    </ul>
  );
}

function EmptyCalendarMessage({ scope }: { scope: EarningsScope }) {
  return (
    <div className="rounded-xl border border-dashed border-border-muted bg-surface-secondary/30 px-4 py-8 text-center text-sm text-text-secondary">
      No earnings events are available for {scope === "all" ? "this window" : `your ${scope}`} yet.
      Run{" "}
      <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-xs">stockviz earnings</code> to
      refresh provider data.
    </div>
  );
}

/** Weeks start on Monday, so a trading week reads left to right. */
const DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

/** Days since the Monday of `date`'s week (UTC). */
function daysSinceMonday(date: Date): number {
  return (date.getUTCDay() + 6) % 7;
}

function monthCells(anchor: Date): Date[] {
  const first = new Date(Date.UTC(anchor.getUTCFullYear(), anchor.getUTCMonth(), 1));
  const last = new Date(Date.UTC(anchor.getUTCFullYear(), anchor.getUTCMonth() + 1, 0));
  const start = new Date(first);
  start.setUTCDate(first.getUTCDate() - daysSinceMonday(first));
  // Five rows when the month fits, six when it spills.
  const weeks = Math.ceil((daysSinceMonday(first) + last.getUTCDate()) / 7);
  return Array.from({ length: weeks * 7 }, (_, index) => {
    const day = new Date(start);
    day.setUTCDate(start.getUTCDate() + index);
    return day;
  });
}

/** The UTC date range a view covers; the page fetches exactly this range. */
export function viewRange(anchor: Date, view: EarningsView): { from: string; to: string } {
  if (view === "month") {
    const first = new Date(Date.UTC(anchor.getUTCFullYear(), anchor.getUTCMonth(), 1));
    const last = new Date(Date.UTC(anchor.getUTCFullYear(), anchor.getUTCMonth() + 1, 0));
    return { from: dateKey(first), to: dateKey(last) };
  }
  const start = new Date(anchor);
  if (view === "week") start.setUTCDate(start.getUTCDate() - daysSinceMonday(start));
  return {
    from: dateKey(start),
    to: dateKey(new Date(start.getTime() + (view === "week" ? 6 : 0) * 86400000)),
  };
}

function shiftAnchor(anchor: Date, view: EarningsView, amount: number): Date {
  if (view === "month") {
    return new Date(Date.UTC(anchor.getUTCFullYear(), anchor.getUTCMonth() + amount, 1));
  }
  const next = new Date(anchor);
  next.setUTCDate(next.getUTCDate() + amount * (view === "week" ? 7 : 1));
  return next;
}

function periodTitle(anchor: Date, view: EarningsView): string {
  if (view === "month")
    return anchor.toLocaleDateString("en-US", { month: "long", year: "numeric", timeZone: "UTC" });
  if (view === "day")
    return anchor.toLocaleDateString("en-US", {
      weekday: "long",
      month: "long",
      day: "numeric",
      year: "numeric",
      timeZone: "UTC",
    });
  const start = viewRange(anchor, "week").from;
  const end = viewRange(anchor, "week").to;
  return `${formatDate(start)} – ${formatDate(end)}`;
}
