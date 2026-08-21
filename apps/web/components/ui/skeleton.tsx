import { cn } from "@/lib/utils";

/**
 * Placeholder block for loading states.
 *
 * `aria-hidden` because a screen reader should hear the route's loading
 * message once, not one announcement per shimmering rectangle.
 */
export function Skeleton({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      aria-hidden="true"
      className={cn("animate-pulse rounded-md bg-muted", className)}
      {...props}
    />
  );
}

/** A table-shaped skeleton — the shape most StockViz routes resolve into. */
export function TableSkeleton({ rows = 8, label }: { rows?: number; label: string }) {
  return (
    // <output> is the semantic live region for "result of an ongoing process";
    // it carries role=status implicitly.
    <output aria-live="polite" className="block space-y-3">
      <span className="sr-only">{label}</span>
      <Skeleton className="h-9 w-48" />
      <div className="rounded-lg border p-4">
        <Skeleton className="mb-4 h-5 w-full" />
        {Array.from({ length: rows }, (_, i) => (
          // biome-ignore lint/suspicious/noArrayIndexKey: static placeholder rows
          <Skeleton key={i} className="mb-2.5 h-8 w-full" />
        ))}
      </div>
    </output>
  );
}
