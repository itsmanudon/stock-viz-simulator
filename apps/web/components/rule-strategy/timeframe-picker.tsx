"use client";

/**
 * A6.4: the bars a rule runs on. Daily always; the intraday intervals only
 * where the symbol has stored minutes (`symbol.intraday.intervals`), with the
 * feed's badge, so a rule is never offered bars that do not exist.
 */

import { Label } from "@/components/ui/label";
import { type StrategyTimeframe, timeframeOptions } from "@/lib/rule-strategy";

export function TimeframePicker({
  id,
  value,
  onChange,
  intervals,
  badge,
  loading = false,
}: {
  id: string;
  value: StrategyTimeframe;
  onChange: (next: StrategyTimeframe) => void;
  intervals: readonly string[] | null | undefined;
  badge?: string | null;
  loading?: boolean;
}) {
  const options = timeframeOptions(intervals);
  const intraday = options.length > 1;
  return (
    <div className="space-y-1">
      <Label htmlFor={id} className="text-xs">
        Timeframe
      </Label>
      <select
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value as StrategyTimeframe)}
        aria-describedby={`${id}-hint`}
        className="flex h-10 w-full rounded-sm border border-input bg-transparent px-3 py-2 text-sm"
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
      <p id={`${id}-hint`} className="text-2xs text-text-tertiary">
        {loading
          ? "Checking for intraday bars…"
          : intraday
            ? `Intraday bars stored${badge ? ` (${badge})` : ""}. On intraday bars, daily. reads the last completed session.`
            : "Only daily bars are stored for this symbol."}
      </p>
    </div>
  );
}
