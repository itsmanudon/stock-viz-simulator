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
 * Anatomy is the "Dashboard Flaws" page head: small uppercase eyebrow, large
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
    <header className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
      <div className="min-w-0 max-w-3xl">
        <p className="text-2xs font-semibold tracking-[0.14em] text-brand uppercase">{eyebrow}</p>
        <h1 className="mt-2 text-3xl font-bold tracking-tight">{title}</h1>
        <p className="mt-2 max-w-2xl text-sm leading-6 text-text-secondary">{description}</p>
        {meta ? <div className="mt-2 text-xs text-text-tertiary">{meta}</div> : null}
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
    <nav aria-label={label} className="mt-5 border-b border-border-muted">
      <ul className="flex gap-1 overflow-x-auto">
        {items.map((item) => {
          const active = item.href === current;
          return (
            <li key={item.href}>
              <a
                href={item.href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "inline-flex h-10 items-center border-b-2 px-3 text-sm whitespace-nowrap transition-colors",
                  active
                    ? "border-brand font-medium text-foreground"
                    : "border-transparent text-text-tertiary hover:text-foreground",
                )}
              >
                {item.label}
              </a>
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
    <section className="border-y border-border-muted py-10 sm:border-x sm:px-6">
      <h2 className="text-base font-semibold">{title}</h2>
      <div className="mt-2 max-w-2xl text-sm leading-6 text-text-secondary">{children}</div>
      {action ? <div className="mt-5">{action}</div> : null}
    </section>
  );
}
