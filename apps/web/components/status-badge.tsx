import { cn } from "@/lib/utils";

export type BadgeTone = "positive" | "negative" | "brand" | "neutral";

const TONE_CLASSES: Record<BadgeTone, string> = {
  positive: "bg-positive/15 text-positive",
  negative: "bg-negative/15 text-negative",
  brand: "bg-brand/15 text-brand",
  neutral: "bg-surface-secondary text-text-secondary",
};

/**
 * Small uppercase status chip used in table cells.
 *
 * Order side, order type, order status, and alert status were four separate
 * components with the same markup and diverging colour maps. This is the one
 * implementation; callers map their domain value to a tone.
 *
 * Distinct from `DeltaPill`, which is the rounded numeric-change chip on the
 * dashboard — this one is squared-off and labels a state, not a number.
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
        "inline-flex items-center rounded-sm px-1.5 py-0.5 text-2xs font-semibold tracking-wide uppercase",
        TONE_CLASSES[tone],
        className,
      )}
    >
      {label}
    </span>
  );
}
