import Link from "next/link";

import { DeltaPill } from "@/components/dashboard/delta-pill";
import { cn } from "@/lib/utils";

/**
 * Card layout for symbol tables on narrow screens.
 *
 * The markets and screener tables are 500px+ wide at their narrowest useful
 * configuration, so on a phone they either overflow the viewport or collapse
 * to two legible columns. A card per symbol keeps every figure readable
 * without horizontal scrolling, and gives each row a real tap target.
 *
 * Rendered under `md`; the table takes over above it. Both render the same
 * data, so nothing is hidden from mobile — it is re-laid out.
 */

export type CardMetric = {
  label: string;
  value: string;
  /** Colour the value by sign; omit for plain figures like RSI or volume. */
  signedBy?: number | null;
};

export type SymbolCardData = {
  ticker: string;
  name: string;
  /** Headline figure, already formatted (e.g. "$188.38"). */
  price: string | null;
  /** Signed change rendered as a pill next to the price. */
  changePct: number | null;
  changeLabel?: string | null;
  /** Small facts laid out in a grid under the headline. */
  metrics?: CardMetric[];
  /** Optional trailing visual, typically a sparkline. */
  visual?: React.ReactNode;
};

function toneClass(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return "text-text-tertiary";
  }
  if (value > 0) return "text-positive";
  if (value < 0) return "text-negative";
  return "text-foreground";
}

export function SymbolCard({ row }: { row: SymbolCardData }) {
  return (
    <li className="border-b border-border-muted last:border-b-0">
      <Link
        href={`/stocks/${encodeURIComponent(row.ticker)}`}
        className="grid grid-cols-[minmax(0,1fr)_auto] gap-x-3 gap-y-2 py-3 transition-colors hover:bg-surface-hover focus-visible:bg-surface-hover sm:py-3.5"
      >
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <span className="block font-mono text-sm font-semibold">{row.ticker}</span>
            <span className="mt-0.5 block truncate text-xs text-text-secondary">{row.name}</span>
          </div>
          <div className="flex shrink-0 flex-col items-end gap-1">
            <span className="font-mono text-sm font-semibold" data-financial>
              {row.price ?? "—"}
            </span>
            {row.changeLabel ? (
              <DeltaPill
                value={row.changeLabel}
                tone={
                  row.changePct === null || row.changePct === undefined
                    ? "neutral"
                    : row.changePct > 0
                      ? "positive"
                      : row.changePct < 0
                        ? "negative"
                        : "neutral"
                }
              />
            ) : null}
          </div>
        </div>

        {row.metrics && row.metrics.length > 0 ? (
          <dl
            className={cn(
              "col-span-2 grid gap-x-3 gap-y-1.5 border-t border-border-muted pt-2.5",
              // Match the column count to the data so a two-metric card
              // doesn't leave a dead third column.
              row.metrics.length <= 2 ? "grid-cols-2" : "grid-cols-3",
            )}
          >
            {row.metrics.map((metric) => (
              <div key={metric.label} className="min-w-0">
                <dt className="inline truncate text-3xs font-semibold tracking-[0.1em] text-text-tertiary uppercase">
                  {metric.label}
                </dt>
                <dd
                  className={cn(
                    "ml-1 inline truncate font-mono text-xs",
                    metric.signedBy === undefined ? "text-foreground" : toneClass(metric.signedBy),
                  )}
                  data-financial
                >
                  {metric.value}
                </dd>
              </div>
            ))}
          </dl>
        ) : null}

        {row.visual ? <div className="col-span-2 hidden pt-0.5 sm:block">{row.visual}</div> : null}
      </Link>
    </li>
  );
}

export function SymbolCardList({
  rows,
  className,
}: {
  rows: SymbolCardData[];
  className?: string;
}) {
  return (
    <ul className={cn("border-y border-border-muted", className)}>
      {rows.map((row) => (
        <SymbolCard key={row.ticker} row={row} />
      ))}
    </ul>
  );
}

/**
 * Sort control for the card list.
 *
 * The table communicates sort through its column headers, which the cards
 * don't have — without this, mobile silently loses the ability to sort at all.
 * Links, not buttons, so it works the same server-rendered way the headers do.
 */
export function CardSortBar({
  options,
  activeKey,
  direction,
  label = "Sort",
}: {
  options: { key: string; label: string; href: string }[];
  activeKey: string;
  direction: "asc" | "desc";
  label?: string;
}) {
  return (
    <nav aria-label={label} className="flex flex-wrap items-center gap-1.5">
      <span className="text-3xs font-semibold tracking-[0.1em] text-text-tertiary uppercase">
        {label}
      </span>
      {options.map((option) => {
        const active = option.key === activeKey;
        return (
          <Link
            key={option.key}
            href={option.href}
            aria-current={active ? "true" : undefined}
            className={cn(
              "inline-flex items-center gap-1 rounded-md border px-2.5 py-1 text-xs transition-colors",
              active
                ? "border-primary bg-primary font-semibold text-primary-foreground"
                : "border-border-muted text-text-secondary hover:bg-surface-hover hover:text-foreground",
            )}
          >
            {option.label}
            {active ? <span aria-hidden>{direction === "asc" ? "↑" : "↓"}</span> : null}
          </Link>
        );
      })}
    </nav>
  );
}
