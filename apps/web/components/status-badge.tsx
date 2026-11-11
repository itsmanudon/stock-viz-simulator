import { cn } from "@/lib/utils";

export type BadgeTone = "positive" | "negative" | "brand" | "warning" | "neutral";

const TONE_CLASSES: Record<BadgeTone, string> = {
  positive: "bg-positive/15 text-positive",
  negative: "bg-negative/15 text-negative",
  brand: "bg-brand/15 text-brand",
  warning: "bg-warning/15 text-warning",
  neutral: "bg-surface-secondary text-text-secondary",
};

const DOT_CLASSES: Record<BadgeTone, string> = {
  positive: "bg-positive",
  negative: "bg-negative",
  brand: "bg-brand",
  warning: "bg-warning",
  neutral: "bg-text-tertiary",
};

/**
 * Small uppercase status chip used in table cells.
 *
 * Order side, order type, order status, and alert status were four separate
 * components with the same markup and diverging colour maps. This is the one
 * implementation; callers map their domain value to a tone.
 *
 * Distinct from `DeltaPill`, which is the numeric-change chip on the
 * dashboard: this one labels a state, not a number. Aurora board v3 gives it
 * a leading dot, so the state reads from shape as well as colour.
 */
export function StatusBadge({
  label,
  tone = "neutral",
  className,
}: {
  label: string;
  tone?: BadgeTone;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-2xs font-semibold tracking-wide whitespace-nowrap uppercase",
        TONE_CLASSES[tone],
        className,
      )}
    >
      <span aria-hidden className={cn("size-1.5 shrink-0 rounded-full", DOT_CLASSES[tone])} />
      {label}
    </span>
  );
}
