import { cn } from "@/lib/utils";

export type Figure = {
  label: string;
  value: React.ReactNode;
  /** A short qualifier under the value: a period, a method, a date. */
  note?: React.ReactNode;
};

/**
 * A row of headline figures sharing one bordered strip (Aurora board v3, the
 * "figure strip"). Cells wrap onto new rows on narrow screens; the hairlines
 * between them come from the 1px gap over the border colour, so a wrapped row
 * keeps its dividers.
 *
 * Values are plain nodes so callers keep control of sign colour and currency;
 * the strip only sets the tabular figure font.
 */
export function FigureStrip({
  figures,
  label,
  className,
}: {
  figures: readonly Figure[];
  /** Accessible name for the list, e.g. "Market breadth". */
  label: string;
  className?: string;
}) {
  if (figures.length === 0) return null;
  return (
    <dl
      aria-label={label}
      className={cn(
        "grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-border-muted bg-border-muted sm:grid-cols-[repeat(auto-fit,minmax(9rem,1fr))]",
        className,
      )}
    >
      {figures.map((figure) => (
        <div key={figure.label} className="flex min-w-0 flex-col gap-0.5 bg-card px-4 py-3">
          <dt className="text-2xs text-text-tertiary">{figure.label}</dt>
          <dd className="truncate font-mono text-base font-medium tabular-nums" data-financial>
            {figure.value}
          </dd>
          {figure.note ? <span className="text-2xs text-text-tertiary">{figure.note}</span> : null}
        </div>
      ))}
    </dl>
  );
}
