import { cn } from "@/lib/utils";

/**
 * Where a price sits inside a range, drawn as a marker on a track (Aurora
 * board v3: the screener's 52-week columns and compare's "52w pos." become
 * one bar). Monochrome on purpose: a position is not a gain or a loss.
 *
 * `positionPct` is 0 at the low and 100 at the high, clamped. The text label
 * is always present for assistive tech; `low`/`high` add the end values.
 */
export function RangeBar({
  positionPct,
  low,
  high,
  label,
  className,
}: {
  positionPct: number | null;
  low?: string;
  high?: string;
  /** Spoken description, e.g. "52-week range: 68% of the way from low to high". */
  label: string;
  className?: string;
}) {
  if (positionPct === null || !Number.isFinite(positionPct)) {
    return <span className="text-text-tertiary">—</span>;
  }
  const clamped = Math.min(100, Math.max(0, positionPct));
  return (
    <span className={cn("grid w-36 gap-1", className)} role="img" aria-label={label}>
      <span className="relative h-1 rounded-full bg-surface-secondary" aria-hidden>
        <span
          className="absolute -top-1 h-3 w-0.5 -translate-x-1/2 rounded-full bg-foreground"
          style={{ left: `${clamped}%` }}
        />
      </span>
      {low !== undefined && high !== undefined ? (
        <span
          className="flex justify-between gap-2 font-mono text-3xs text-text-tertiary tabular-nums"
          aria-hidden
        >
          <span>{low}</span>
          <span>{high}</span>
        </span>
      ) : (
        <span className="font-mono text-3xs text-text-tertiary tabular-nums" aria-hidden>
          {clamped.toFixed(0)}% of range
        </span>
      )}
    </span>
  );
}

/** Position of `value` between `low` and `high`, as 0–100; null when undefined. */
export function rangePositionPct(
  value: number | null,
  low: number | null,
  high: number | null,
): number | null {
  if (value === null || low === null || high === null) return null;
  if (![value, low, high].every(Number.isFinite) || high <= low) return null;
  return ((value - low) / (high - low)) * 100;
}
