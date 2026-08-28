import { ArrowUpRight } from "lucide-react";
import Link from "next/link";

import { cn } from "@/lib/utils";

/**
 * One tile of the dashboard bento grid.
 *
 * Mirrors the card anatomy shared by the Financial Dashboard and Dashboard
 * Flaws references: a title row with an optional trailing action, then the
 * body. `action` renders as a "View all →" style link when given an href.
 */
export function WidgetCard({
  title,
  titleId,
  action,
  className,
  children,
}: React.PropsWithChildren<{
  title: string;
  /** Ties the card's heading to its section landmark. */
  titleId: string;
  action?: { label: string; href: string };
  className?: string;
}>) {
  return (
    <section
      aria-labelledby={titleId}
      className={cn(
        "flex min-w-0 flex-col rounded-lg border border-border-muted bg-card p-4 sm:p-5",
        className,
      )}
    >
      <div className="flex items-center justify-between gap-3">
        <h2 id={titleId} className="text-sm font-semibold">
          {title}
        </h2>
        {action ? (
          <Link
            href={action.href}
            className="group inline-flex shrink-0 items-center gap-0.5 text-xs font-medium text-text-secondary transition-colors hover:text-brand"
          >
            {action.label}
            <ArrowUpRight className="size-3.5 transition-transform group-hover:-translate-y-px" />
          </Link>
        ) : null}
      </div>
      <div className="mt-4 min-w-0 flex-1">{children}</div>
    </section>
  );
}

/** Centred placeholder for a widget whose data is empty or unavailable. */
export function WidgetEmpty({ children }: React.PropsWithChildren) {
  return (
    <p className="flex h-full min-h-20 items-center justify-center px-2 py-4 text-center text-xs leading-5 text-text-tertiary">
      {children}
    </p>
  );
}
