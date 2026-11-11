import { PageEmptyState, PageHeader, PageSubnav } from "@/components/page-header";
import { type BadgeTone, StatusBadge } from "@/components/status-badge";
import { MONITORING_SUBNAV, OPERATIONAL_SUBNAV } from "@/lib/operational-trading";

/**
 * Operational-trading flavour of the shared page chrome.
 *
 * The layout lives in `page-header.tsx`; this module only supplies the
 * domain's subnav items and the badge tone maps for order/alert state.
 */
export function OperationalPageHeader(props: {
  eyebrow: string;
  title: string;
  description: string;
  meta?: React.ReactNode;
  actions?: React.ReactNode;
}) {
  return <PageHeader {...props} />;
}

export function OperationalSubnav({ current }: { current: "/trade" | "/orders" }) {
  return <PageSubnav items={OPERATIONAL_SUBNAV} current={current} label="Trading tools" />;
}

export function MonitoringSubnav({ current }: { current: "/watchlist" | "/alerts" }) {
  return <PageSubnav items={MONITORING_SUBNAV} current={current} label="Monitoring tools" />;
}

export function OperationalEmptyState(props: {
  title: string;
  children: React.ReactNode;
  action?: React.ReactNode;
}) {
  return <PageEmptyState {...props} />;
}

export function OrderTypeBadge({ type }: { type: string }) {
  return <StatusBadge label={type.replaceAll("_", " ")} />;
}

/**
 * Buy or sell, as a neutral label with a direction arrow: the side of an
 * order is not a gain or a loss, so it never takes those colours.
 */
export function OrderSideBadge({ side }: { side: "buy" | "sell" }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-2xs font-semibold tracking-wide text-text-secondary uppercase">
      <span
        aria-hidden
        className="inline-grid size-5 place-items-center rounded-md border border-border-muted bg-surface-secondary text-2xs"
      >
        {side === "buy" ? "↗" : "↘"}
      </span>
      <span>{side}</span>
    </span>
  );
}

// Pending is waiting on the next close: the warning tone, not the brand,
// which is kept for identity and selected controls.
const ORDER_STATUS_TONES: Record<string, BadgeTone> = {
  pending: "warning",
  filled: "positive",
  cancelled: "neutral",
};

export function OrderStatusBadge({ status }: { status: string }) {
  return <StatusBadge label={status} tone={ORDER_STATUS_TONES[status] ?? "neutral"} />;
}

export function AlertStatusBadge({
  triggered,
  dismissed,
}: {
  triggered: boolean;
  dismissed: boolean;
}) {
  if (dismissed) return <StatusBadge label="Dismissed" tone="neutral" />;
  if (triggered) return <StatusBadge label="Triggered" tone="positive" />;
  return <StatusBadge label="Active" tone="brand" />;
}
