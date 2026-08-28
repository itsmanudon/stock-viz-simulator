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

export function OrderSideBadge({ side }: { side: "buy" | "sell" }) {
  return <StatusBadge label={side} tone={side === "buy" ? "positive" : "negative"} />;
}

const ORDER_STATUS_TONES: Record<string, BadgeTone> = {
  pending: "brand",
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
