"use client";

import type { CalendarDay } from "@/lib/journal-view-model";
import { describeDay, formatCompactPnl, tintFor } from "@/lib/journal-view-model";
import { cn } from "@/lib/utils";

/**
 * One date in the P&L calendar.
 *
 * A real `<button>` when it holds data, an inert `<div>` when it pads the grid
 * — so keyboard users tab past spacers instead of landing on them. The tint
 * comes from `.pnl-tint` in globals.css; nothing here names a colour.
 *
 * Only the P&L and the trade count are permanently visible. Winners, losers,
 * and win rate live in the inspector, because a cell that shows five numbers
 * at 11px shows none of them.
 */
export function PnlCalendarDay({
  day,
  scale,
  selected,
  onSelect,
  onKeyDown,
}: {
  day: CalendarDay;
  /** Month-local tint reference; see `tintScale`. */
  scale: number;
  selected: boolean;
  onSelect: (date: string) => void;
  onKeyDown: (event: React.KeyboardEvent<HTMLButtonElement>, date: string) => void;
}) {
  if (!day.inMonth) {
    return (
      <div aria-hidden className="min-h-16 rounded-md border border-transparent sm:min-h-24" />
    );
  }

  const stats = day.summary?.stats ?? null;
  const pnl = stats ? Number(stats.realized_pnl) : 0;
  const tint = stats ? tintFor(pnl, scale) : { sign: "flat" as const, level: 0 as const };
  const hasActivity = Boolean(stats && stats.trade_count > 0);

  return (
    <button
      type="button"
      data-date={day.date}
      data-testid={`journal-day-${day.date}`}
      data-sign={tint.sign}
      data-level={tint.level}
      aria-pressed={selected}
      aria-label={describeDay(day.date, stats)}
      onClick={() => onSelect(day.date)}
      onKeyDown={(event) => onKeyDown(event, day.date)}
      className={cn(
        "pnl-tint group flex min-w-0 min-h-16 flex-col items-start rounded-md border p-1 text-left transition-colors duration-150 sm:min-h-24 sm:p-2.5",
        "border-border-muted hover:bg-surface-hover focus-visible:z-10 focus-visible:ring-2 focus-visible:ring-ring",
        day.isWeekend && !hasActivity && "opacity-55",
        selected && "ring-2 ring-ring ring-offset-1 ring-offset-background",
      )}
    >
      <span
        className={cn(
          "font-mono text-2xs tabular-nums sm:text-xs",
          day.isToday
            ? "-mx-0.5 rounded-sm bg-brand px-1 font-semibold text-primary-foreground"
            : hasActivity
              ? "text-text-secondary"
              : "text-text-tertiary",
        )}
      >
        {day.dayOfMonth}
      </span>

      {hasActivity && stats ? (
        <span className="mt-auto flex w-full min-w-0 flex-col">
          <span
            data-financial
            className={cn(
              "truncate font-mono text-xs font-semibold sm:text-sm",
              pnl > 0 ? "text-positive" : pnl < 0 ? "text-negative" : "text-text-secondary",
            )}
          >
            {/* Compact on the narrow grid, exact in the inspector — the sign
                is always spelled out so colour is never the only cue. */}
            <span className="journal-pnl-compact">
              {formatCompactPnl(pnl).replace("$", "").replace(".0k", "k")}
            </span>
            <span className="journal-pnl-full">
              {pnl > 0 ? "+" : pnl < 0 ? "−" : ""}
              {Math.abs(pnl).toLocaleString("en-US", {
                style: "currency",
                currency: "USD",
                minimumFractionDigits: 0,
                maximumFractionDigits: 0,
              })}
            </span>
          </span>
          <span className="hidden truncate font-mono text-3xs text-text-tertiary sm:block">
            {stats.trade_count} {stats.trade_count === 1 ? "trade" : "trades"}
          </span>
        </span>
      ) : null}
    </button>
  );
}
