import { MONITORING_SUBNAV, OPERATIONAL_SUBNAV } from "@/lib/operational-trading";
import { cn } from "@/lib/utils";

export function OperationalPageHeader({
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
        <h1 className="mt-2 text-3xl font-semibold tracking-tight">{title}</h1>
        <p className="mt-2 max-w-2xl text-sm leading-6 text-text-secondary">{description}</p>
        {meta ? <div className="mt-2 text-xs text-text-tertiary">{meta}</div> : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </header>
  );
}

function Subnav({
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

export function OperationalSubnav({ current }: { current: "/trade" | "/orders" }) {
  return <Subnav items={OPERATIONAL_SUBNAV} current={current} label="Trading tools" />;
}

export function MonitoringSubnav({ current }: { current: "/watchlist" | "/alerts" }) {
  return <Subnav items={MONITORING_SUBNAV} current={current} label="Monitoring tools" />;
}

export function OperationalEmptyState({
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

export function OrderTypeBadge({ type }: { type: string }) {
  return (
    <span className="inline-flex items-center rounded-sm bg-surface-secondary px-1.5 py-0.5 text-2xs font-semibold tracking-wide text-text-secondary uppercase">
      {type.replaceAll("_", " ")}
    </span>
  );
}

export function OrderSideBadge({ side }: { side: "buy" | "sell" }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-sm px-1.5 py-0.5 text-2xs font-semibold tracking-wide uppercase",
        side === "buy" ? "bg-positive/15 text-positive" : "bg-negative/15 text-negative",
      )}
    >
      {side}
    </span>
  );
}

export function OrderStatusBadge({ status }: { status: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-sm px-1.5 py-0.5 text-2xs font-semibold tracking-wide uppercase",
        status === "pending" && "bg-brand/15 text-brand",
        status === "filled" && "bg-positive/15 text-positive",
        status === "cancelled" && "bg-surface-secondary text-text-secondary",
      )}
    >
      {status}
    </span>
  );
}

export function AlertStatusBadge({
  triggered,
  dismissed,
}: {
  triggered: boolean;
  dismissed: boolean;
}) {
  const label = triggered ? (dismissed ? "Dismissed" : "Triggered") : "Active";
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-sm px-1.5 py-0.5 text-2xs font-semibold tracking-wide uppercase",
        !triggered && "bg-brand/15 text-brand",
        triggered && !dismissed && "bg-positive/15 text-positive",
        dismissed && "bg-surface-secondary text-text-secondary",
      )}
    >
      {label}
    </span>
  );
}
