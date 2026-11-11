import { cn } from "@/lib/utils";

/**
 * The count beside a tab label, e.g. "Orders 3" (Aurora board v3: tabs with
 * counts). A rounded mono chip, so the number reads as a tally, not as part
 * of the label. Renders nothing for zero unless `showZero` is set, matching
 * how the tabs have always hidden empty counts.
 */
export function CountBadge({
  count,
  showZero = false,
  className,
}: {
  count: number;
  showZero?: boolean;
  className?: string;
}) {
  if (!count && !showZero) return null;
  return (
    <span
      className={cn(
        "ml-1.5 inline-grid min-w-5 place-items-center rounded-full bg-surface-secondary px-1.5 font-mono text-2xs leading-5 text-text-secondary tabular-nums",
        className,
      )}
    >
      {count}
    </span>
  );
}
