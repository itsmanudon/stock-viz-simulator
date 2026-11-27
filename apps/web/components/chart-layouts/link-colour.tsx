"use client";

/**
 * A6.8: the seven link colours (the watchlist tags, `--list-<name>` tokens)
 * as a dot and a native select (keyboard and screen reader friendly).
 */

import { LINK_COLOURS, type LinkColour, isLinkColour } from "@/lib/chart-layouts";
import { cn } from "@/lib/utils";
import { listColourVar } from "@/lib/watchlist-columns";

export function LinkDot({ colour, className }: { colour: LinkColour; className?: string }) {
  return (
    <span
      aria-hidden
      className={cn("inline-block size-2.5 shrink-0 rounded-full", className)}
      style={{ backgroundColor: listColourVar(colour) }}
    />
  );
}

export function LinkColourSelect({
  label,
  value,
  onChange,
  testId,
}: {
  label: string;
  value: LinkColour | null;
  onChange: (next: LinkColour | null) => void;
  testId?: string;
}) {
  return (
    <span className="inline-flex items-center gap-1.5">
      {value ? (
        <LinkDot colour={value} />
      ) : (
        <span
          aria-hidden
          className="inline-block size-2.5 rounded-full border border-border-muted"
        />
      )}
      <select
        aria-label={label}
        value={value ?? ""}
        onChange={(event) => onChange(isLinkColour(event.target.value) ? event.target.value : null)}
        className="h-8 rounded-md border border-border-muted bg-card px-2 text-xs font-medium text-foreground hover:bg-surface-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/60"
        data-testid={testId}
      >
        <option value="">Unlinked</option>
        {LINK_COLOURS.map((colour) => (
          <option key={colour.key} value={colour.key}>
            {colour.label}
          </option>
        ))}
      </select>
    </span>
  );
}
