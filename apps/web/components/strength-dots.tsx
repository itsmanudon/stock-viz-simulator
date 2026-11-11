import { cn } from "@/lib/utils";

/**
 * Signal strength as one dot per vote (Aurora board v3), filled for each
 * supporting check, with the count beside it. The dots match the seven checks
 * the detail panel lists, so the two read as the same thing.
 */
export function StrengthDots({
  score,
  max,
  dotsFrom = "always",
  className,
}: {
  score: number;
  max: number;
  /** "md" hides the dots on phones, where a row needs the width for its name (audit D2). */
  dotsFrom?: "always" | "md";
  className?: string;
}) {
  const filled = Math.max(0, Math.min(max, Math.round(score)));
  return (
    <span className={cn("inline-flex items-center gap-2", className)}>
      <span
        className={cn("gap-0.5", dotsFrom === "md" ? "hidden md:inline-flex" : "inline-flex")}
        aria-hidden
      >
        {Array.from({ length: max }, (_, index) => (
          <span
            // biome-ignore lint/suspicious/noArrayIndexKey: fixed-length, never reordered
            key={index}
            className={cn(
              "size-1.5 rounded-full border",
              index < filled ? "border-foreground bg-foreground" : "border-border bg-transparent",
            )}
          />
        ))}
      </span>
      <span className="font-mono text-xs tabular-nums">
        {filled}/{max}
      </span>
    </span>
  );
}
