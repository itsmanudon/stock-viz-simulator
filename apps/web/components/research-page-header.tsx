import { RESEARCH_SUBNAV } from "@/lib/app-navigation";
import { cn } from "@/lib/utils";

export function ResearchPageHeader({
  title,
  description,
  meta,
  actions,
}: {
  title: string;
  description: string;
  meta?: React.ReactNode;
  actions?: React.ReactNode;
}) {
  return (
    <header className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
      <div className="min-w-0 max-w-3xl">
        <p className="text-[11px] font-semibold tracking-[0.14em] text-brand uppercase">Research</p>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight">{title}</h1>
        <p className="mt-2 max-w-2xl text-sm leading-6 text-text-secondary">{description}</p>
        {meta ? <div className="mt-2 text-xs text-text-tertiary">{meta}</div> : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </header>
  );
}

export function ResearchSubnav({ current }: { current: string }) {
  return (
    <nav aria-label="Research tools" className="mt-5 border-b border-border-muted">
      <ul className="flex gap-1 overflow-x-auto">
        {RESEARCH_SUBNAV.map((item) => {
          const active = item.href === current;
          return (
            <li key={item.href}>
              <a
                href={item.href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "inline-flex h-10 items-center border-b-2 px-3 text-sm transition-colors",
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

export function ResearchEmptyState({
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

export function ResearchSectionHeader({
  title,
  description,
  id,
}: {
  title: string;
  description?: string;
  id?: string;
}) {
  return (
    <div className="mb-3">
      <h2 id={id} className="text-sm font-semibold tracking-tight">
        {title}
      </h2>
      {description ? (
        <p className="mt-1 text-xs leading-5 text-text-tertiary">{description}</p>
      ) : null}
    </div>
  );
}
