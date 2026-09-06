"use client";

import type { JournalWeekSummary } from "@/lib/api/journal";
import { formatRangeLabel } from "@/lib/journal-view-model";
import { cn } from "@/lib/utils";

/**
 * The week roll-up for a calendar row.
 *
 * Two shapes, one component: a column beside the week on wide screens, and a
 * full-width strip under the week when there is no room for a ninth column.
 * The strip is why the mobile calendar keeps its weekly aggregate instead of
 * dropping it or forcing the page to scroll sideways.
 *
 * Deliberately not tinted: a fourth block of colour per row would stop the day
 * cells being the thing you read first.
 */
export function WeeklySummaryCell({
  week,
  variant,
  selected,
  onSelect,
}: {
  week: JournalWeekSummary | null;
  variant: "column" | "row";
  selected: boolean;
  onSelect: (start: string) => void;
}) {
  const column = variant === "column";
  const visibility = column ? "journal-week-column" : "journal-week-strip flex";

  if (!week) return <div aria-hidden className={column ? "journal-week-column" : "h-8"} />;

  const pnl = Number(week.stats.realized_pnl);
  const count = week.stats.trade_count;
  const range = formatRangeLabel(week.start, week.end);

  if (count === 0) {
    // A silent week keeps the row's shape on wide screens and disappears
    // entirely on narrow ones, where vertical space is the scarce thing.
    return column ? (
      <div
        aria-hidden
        className="journal-week-column min-h-24 items-center rounded-md border border-dashed border-border-muted px-3"
      >
        <span className="font-mono text-3xs text-text-tertiary">No trades</span>
      </div>
    ) : (
      <div aria-hidden className="journal-week-strip h-8" />
    );
  }

  const amount = Math.abs(pnl).toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  const tone = pnl > 0 ? "text-positive" : pnl < 0 ? "text-negative" : "text-text-secondary";
  const sign = pnl > 0 ? "+" : pnl < 0 ? "−" : "";

  return (
    <button
      type="button"
      data-testid={column ? `journal-week-${week.start}` : undefined}
      aria-pressed={selected}
      aria-label={`Week of ${range}, ${
        pnl >= 0 ? "profit" : "loss"
      } ${Math.abs(pnl).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} dollars, ${count} ${count === 1 ? "trade" : "trades"}`}
      onClick={() => onSelect(week.start)}
      className={cn(
        visibility,
        "rounded-md border border-border-muted bg-surface-secondary text-left focus-visible:ring-2 focus-visible:ring-ring transition-colors duration-150 hover:bg-surface-hover",
        selected && "ring-2 ring-ring ring-offset-1 ring-offset-background",
        column
          ? "min-h-24 flex-col justify-center px-3"
          : "w-full min-h-8 items-baseline justify-between gap-3 px-2.5 py-1.5",
      )}
    >
      {column ? (
        <>
          <span className="font-mono text-3xs uppercase tracking-wide text-text-tertiary">
            Week
          </span>
          <span
            data-financial
            className={cn("mt-0.5 truncate font-mono text-sm font-semibold", tone)}
          >
            {sign}
            {amount}
          </span>
          <span className="font-mono text-3xs text-text-tertiary">
            {count} {count === 1 ? "trade" : "trades"}
          </span>
        </>
      ) : (
        <>
          <span className="font-mono text-3xs uppercase tracking-wide text-text-tertiary">
            Week of {formatRangeLabel(week.start, week.end)}
          </span>
          <span data-financial className={cn("shrink-0 font-mono text-xs font-semibold", tone)}>
            {sign}
            {amount}
            <span className="ml-1.5 font-normal text-text-tertiary">· {count}</span>
          </span>
        </>
      )}
    </button>
  );
}
