"use client";

import { ChevronLeft, ChevronRight } from "lucide-react";
import { useCallback, useRef } from "react";

import { PnlCalendarDay } from "@/components/journal/pnl-calendar-day";
import { WeeklySummaryCell } from "@/components/journal/weekly-summary-cell";
import { Button } from "@/components/ui/button";
import type { JournalMonth } from "@/lib/api/journal";
import {
  type MonthKey,
  buildCalendar,
  currentMonthKey,
  formatMonthLabel,
  monthKeyOf,
  shiftMonth,
  splitMonthKey,
  tintScale,
} from "@/lib/journal-view-model";

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

/** Years offered in the picker, oldest first. StockViz has no data before 2020. */
function yearOptions(current: number): number[] {
  const thisYear = splitMonthKey(currentMonthKey()).year;
  const newest = Math.max(thisYear, current);
  const years: number[] = [];
  for (let year = Math.min(2020, current); year <= newest; year++) years.push(year);
  return years;
}

const MONTH_NAMES = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
];

/**
 * The month grid: a Monday-first calendar with a week roll-up per row.
 *
 * The grid is built from the month key alone, so it keeps its exact dimensions
 * while data loads or fails — no layout jump between skeleton, data, and
 * error. `data` only fills the cells in.
 *
 * Weekends stay in the grid (muted when idle) because a market order fills at
 * the latest close on any calendar day, so a Saturday fill is real data that
 * must not be hidden.
 */
export function PnlCalendar({
  monthKey,
  data,
  loading,
  selectedDate,
  selectedWeek,
  onMonthChange,
  onSelectDay,
  onSelectWeek,
}: {
  monthKey: MonthKey;
  data: JournalMonth | null;
  loading: boolean;
  selectedDate: string | null;
  selectedWeek: string | null;
  onMonthChange: (next: MonthKey) => void;
  onSelectDay: (date: string) => void;
  onSelectWeek: (start: string) => void;
}) {
  const gridRef = useRef<HTMLDivElement>(null);
  const { year, month } = splitMonthKey(monthKey);
  const weeks = buildCalendar(monthKey, data);
  const scale = tintScale((data?.days ?? []).map((day) => Number(day.stats.realized_pnl)));
  const isCurrentMonth = monthKey === currentMonthKey();

  /**
   * Arrow keys walk the grid a day at a time; Home/End jump to the row's ends.
   * Focus moves by looking the target date up in the DOM rather than tracking
   * a roving index, so a padded or missing cell simply has nothing to focus
   * and the caret stays put.
   */
  const handleKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLButtonElement>, date: string) => {
      const deltas: Record<string, number> = {
        ArrowLeft: -1,
        ArrowRight: 1,
        ArrowUp: -7,
        ArrowDown: 7,
      };
      const delta = deltas[event.key];
      if (delta === undefined && event.key !== "Home" && event.key !== "End") return;

      event.preventDefault();
      const cells = Array.from(
        gridRef.current?.querySelectorAll<HTMLButtonElement>("[data-date]") ?? [],
      );
      const index = cells.findIndex((cell) => cell.dataset.date === date);
      if (index < 0) return;

      let target = index;
      const weekday = (new Date(`${date}T00:00:00Z`).getUTCDay() + 6) % 7;
      if (delta !== undefined) target = index + delta;
      else if (event.key === "Home") target = index - weekday;
      else target = index - weekday + 6;

      cells[Math.max(0, Math.min(cells.length - 1, target))]?.focus();
    },
    [],
  );

  return (
    <section aria-labelledby="journal-calendar-heading" className="journal-calendar min-w-0">
      <div className="flex flex-wrap items-center justify-between gap-3 pb-3">
        <h3 id="journal-calendar-heading" className="text-sm font-semibold tracking-tight">
          {formatMonthLabel(monthKey)}
          <span className="sr-only"> profit and loss calendar</span>
        </h3>

        <div className="flex flex-wrap items-center gap-1.5">
          <Button
            variant="outline"
            size="icon"
            aria-label="Previous month"
            disabled={monthKey === "1970-01"}
            onClick={() => onMonthChange(shiftMonth(monthKey, -1))}
          >
            <ChevronLeft className="size-4" aria-hidden />
          </Button>

          <label className="sr-only" htmlFor="journal-month-select">
            Month
          </label>
          <select
            id="journal-month-select"
            value={month}
            onChange={(event) => onMonthChange(monthKeyOf(year, Number(event.target.value)))}
            className="h-8 rounded-md border border-border bg-card px-2 text-xs text-foreground focus-visible:ring-2 focus-visible:ring-ring"
          >
            {MONTH_NAMES.map((name, index) => (
              <option key={name} value={index + 1}>
                {name}
              </option>
            ))}
          </select>

          <label className="sr-only" htmlFor="journal-year-select">
            Year
          </label>
          <select
            id="journal-year-select"
            value={year}
            onChange={(event) => onMonthChange(monthKeyOf(Number(event.target.value), month))}
            className="h-8 rounded-md border border-border bg-card px-2 font-mono text-xs text-foreground focus-visible:ring-2 focus-visible:ring-ring"
          >
            {yearOptions(year).map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>

          <Button
            variant="outline"
            size="icon"
            aria-label="Next month"
            disabled={monthKey === "2200-12"}
            onClick={() => onMonthChange(shiftMonth(monthKey, 1))}
          >
            <ChevronRight className="size-4" aria-hidden />
          </Button>

          <Button
            variant="ghost"
            size="sm"
            disabled={isCurrentMonth}
            onClick={() => onMonthChange(currentMonthKey())}
          >
            Today
          </Button>
        </div>
      </div>

      <div className="overflow-x-auto pb-1">
        <div className="min-w-[336px]">
          <div className="journal-calendar-row grid gap-1 pb-1.5" aria-hidden>
            <div className="grid min-w-0 grid-cols-7 gap-1">
              {WEEKDAYS.map((label) => (
                <span
                  key={label}
                  className="px-1 font-mono text-3xs uppercase tracking-wide text-text-tertiary"
                >
                  <span className="sm:hidden">{label.slice(0, 1)}</span>
                  <span className="hidden sm:inline">{label}</span>
                </span>
              ))}
            </div>
            <span className="journal-week-column px-1 font-mono text-3xs uppercase tracking-wide text-text-tertiary">
              Week
            </span>
          </div>

          <div
            ref={gridRef}
            data-loading={loading ? "true" : undefined}
            className="space-y-1 transition-opacity duration-150 data-[loading]:opacity-60"
          >
            {weeks.map((week) => (
              <div key={week.key} className="space-y-1">
                <div className="journal-calendar-row grid gap-1">
                  <div className="grid min-w-0 grid-cols-7 gap-1">
                    {week.days.map((day) => (
                      <PnlCalendarDay
                        key={day.date}
                        day={day}
                        scale={scale}
                        selected={selectedDate === day.date}
                        onSelect={onSelectDay}
                        onKeyDown={handleKeyDown}
                      />
                    ))}
                  </div>
                  <WeeklySummaryCell
                    week={week.summary}
                    variant="column"
                    selected={selectedWeek === week.key}
                    onSelect={onSelectWeek}
                  />
                </div>
                <WeeklySummaryCell
                  week={week.summary}
                  variant="row"
                  selected={selectedWeek === week.key}
                  onSelect={onSelectWeek}
                />
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
