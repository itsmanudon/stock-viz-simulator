import { ArrowDown, ArrowUp, ChevronsUpDown } from "lucide-react";
import Link from "next/link";

import { TableCell, TableHead } from "@/components/ui/table";
import { cn } from "@/lib/utils";

/**
 * Shared table furniture.
 *
 * Every table page had re-derived the same three things by hand: the bordered
 * container, the "right-aligned mono number that turns green or red and falls
 * back to an em dash" cell, and the sortable column header. The tone logic in
 * particular had drifted onto raw `text-green-500` / `text-red-500`, which are
 * not the `--positive` / `--negative` tokens the rest of the app uses.
 *
 * Anatomy follows the "Dashboard Flaws" reference: a toolbar of view controls
 * above a bordered table whose numeric columns are right-aligned and tabular.
 */

/**
 * Bordered, rounded shell around a `<Table>`.
 *
 * `overflow-x-auto` rather than `overflow-hidden`: the inner `Table` primitive
 * has its own scroll container, but a clipping parent means a table wider than
 * its box pushes the whole page into horizontal scrolling instead. Column
 * visibility is tuned so this shouldn't trigger, but a long company name or a
 * translated header shouldn't be able to break the page layout.
 */
export function DataTableFrame({
  className,
  children,
}: React.PropsWithChildren<{ className?: string }>) {
  return (
    <div className={cn("overflow-x-auto rounded-lg border border-border-muted", className)}>
      {children}
    </div>
  );
}

/**
 * Toolbar above a table: view controls on the left, actions on the right.
 *
 * Both slots are optional so a page can use it purely as a result-count bar.
 */
export function TableToolbar({
  children,
  actions,
  className,
}: React.PropsWithChildren<{ actions?: React.ReactNode; className?: string }>) {
  return (
    <div className={cn("flex flex-wrap items-center justify-between gap-3 pb-3", className)}>
      <div className="flex min-w-0 flex-wrap items-center gap-2">{children}</div>
      {actions ? <div className="flex shrink-0 items-center gap-2">{actions}</div> : null}
    </div>
  );
}

type Tone = "positive" | "negative" | "neutral";

function toneClass(tone: Tone): string {
  if (tone === "positive") return "text-positive";
  if (tone === "negative") return "text-negative";
  return "text-foreground";
}

/** Sign of `value`, or "neutral" when it's null/non-finite. */
export function toneForValue(value: number | null | undefined): Tone {
  if (value === null || value === undefined || !Number.isFinite(value)) return "neutral";
  if (value > 0) return "positive";
  if (value < 0) return "negative";
  return "neutral";
}

/**
 * Right-aligned tabular number.
 *
 * `tone` colours the value; omit it (or pass a null `signedBy`) for plain
 * figures like price or volume that shouldn't be tinted. Null children render
 * an em dash in muted text so empty cells read as "no data" rather than zero.
 */
export function NumericCell({
  children,
  signedBy,
  muted,
  className,
  ...props
}: React.ComponentProps<typeof TableCell> & {
  /** Colour the cell by the sign of this number. */
  signedBy?: number | null;
  /** De-emphasise the value (secondary columns like 52w high/low). */
  muted?: boolean;
}) {
  const empty = children === null || children === undefined || children === "—";
  const tone = signedBy === undefined ? "neutral" : toneForValue(signedBy);

  return (
    <TableCell
      className={cn(
        "text-right font-mono",
        empty || muted ? "text-text-tertiary" : toneClass(tone),
        className,
      )}
      data-financial
      {...props}
    >
      {empty ? "—" : children}
    </TableCell>
  );
}

/**
 * Column header that links to the same page with a different sort.
 *
 * Server-rendered: sorting is URL state, so the header is an anchor and works
 * without JavaScript. `direction` is null when this column isn't the active
 * sort, which shows the neutral both-ways affordance.
 */
export function SortableHead({
  href,
  label,
  direction,
  align = "left",
  className,
}: {
  href: string;
  label: string;
  direction: "asc" | "desc" | null;
  align?: "left" | "right";
  className?: string;
}) {
  const Icon = direction === "asc" ? ArrowUp : direction === "desc" ? ArrowDown : ChevronsUpDown;

  return (
    <TableHead
      aria-sort={direction === "asc" ? "ascending" : direction === "desc" ? "descending" : "none"}
      className={cn(align === "right" && "text-right", className)}
    >
      <Link
        href={href}
        className={cn(
          "group inline-flex items-center gap-1 transition-colors hover:text-foreground",
          align === "right" && "flex-row-reverse",
          direction ? "text-foreground" : "text-text-secondary",
        )}
      >
        {label}
        <Icon
          className={cn("size-3 shrink-0", direction ? "text-brand" : "text-text-tertiary")}
          aria-hidden
        />
      </Link>
    </TableHead>
  );
}
