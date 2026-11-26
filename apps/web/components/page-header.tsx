import Link from "next/link";

import { titleCase } from "@/lib/title-case";
import { cn } from "@/lib/utils";

/**
 * The page-header / subnav / empty-state trio shared by every workspace page.
 *
 * `operational-page-header.tsx` and `research-page-header.tsx` had grown
 * independent, byte-identical copies of all three; the Research variant only
 * differed by hard-coding its eyebrow. These are the single implementation —
 * the domain-specific modules re-export thin wrappers that supply their own
 * eyebrow and subnav items.
 *
 * Titles are Geist 600 with -0.025em tracking, matching the stock page's
 * company name (owner's pick, 12 Nov 2026). Anatomy is the "Dashboard Flaws" page head: small Title Case eyebrow, large
 * title, one-line description, optional meta and actions.
 */
export function PageHeader({
  eyebrow,
  title,
  description,
  meta,
  actions,
}: {
  eyebrow: string;
  title: string;
  description: string;
  meta?: React.ReactNode;
  actions?: React.ReactNode;
}) {
  return (
    <header className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
      <div className="min-w-0 max-w-3xl">
        <p className="flex items-center gap-2 font-mono text-2xs font-medium tracking-[0.02em] text-text-secondary">
          <span aria-hidden className="nav-active-bar size-1.5 rounded-full" />
          {titleCase(eyebrow)}
        </p>
        <h1 className="mt-2 text-3xl font-semibold tracking-[-0.04em] sm:text-4xl">{title}</h1>
        <p className="mt-1.5 max-w-2xl text-sm leading-6 text-text-secondary">{description}</p>
        {meta ? <div className="mt-1.5 text-xs text-text-tertiary">{meta}</div> : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </header>
  );
}

/** Underlined tab strip for switching between sibling routes in a domain. */
export function PageSubnav({
  items,
  current,
  label,
}: {
  items: readonly { href: string; label: string }[];
  current: string;
  label: string;
}) {
  return (
    <nav aria-label={label} className="mt-4 border-b border-border-muted">
      <ul className="flex gap-1 overflow-x-auto">
        {items.map((item) => {
          const active = item.href === current;
          return (
            <li key={item.href}>
              {/* Client-side navigation (was a plain <a>, which reloaded the
                  whole document on every tab switch). */}
              <Link
                href={item.href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "relative inline-flex h-10 items-center px-2.5 text-sm whitespace-nowrap transition-colors",
                  active
                    ? "font-medium text-foreground"
                    : "text-text-tertiary hover:text-foreground",
                )}
              >
                {item.label}
                {active ? (
                  <span
                    aria-hidden
                    className="nav-active-bar absolute inset-x-2 -bottom-px h-0.5 rounded-full"
                  />
                ) : null}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

/** Bordered "nothing here yet" panel with an optional call to action. */
export function PageEmptyState({
  title,
  children,
  action,
}: {
  title: string;
  children: React.ReactNode;
  action?: React.ReactNode;
}) {
  return (
    <section className="rounded-xl border border-dashed border-border bg-card/60 px-4 py-10 sm:px-6">
      <h2 className="text-base font-semibold">{title}</h2>
      <div className="mt-2 max-w-2xl text-sm leading-6 text-text-secondary">{children}</div>
      {action ? <div className="mt-5">{action}</div> : null}
    </section>
  );
}

/**
 * A rounded chip for a page header's meta row (Aurora board v3): the date a
 * page's data is from, the zone its times use, or a count. The dot reads
 * freshness or status, never direction; the default is neutral.
 */
export function MetaChip({
  children,
  tone = "neutral",
  className,
}: {
  children: React.ReactNode;
  tone?: "neutral" | "positive" | "warning";
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border border-border-muted px-2.5 py-0.5 text-2xs text-text-secondary",
        className,
      )}
    >
      <span
        aria-hidden
        className={cn(
          "size-1.5 shrink-0 rounded-full",
          tone === "positive"
            ? "bg-positive"
            : tone === "warning"
              ? "bg-warning"
              : "bg-text-tertiary",
        )}
      />
      {children}
    </span>
  );
}
