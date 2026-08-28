import { BellRing } from "lucide-react";
import Link from "next/link";

import { WidgetCard, WidgetEmpty } from "@/components/dashboard/widget-card";
import type { Alert } from "@/lib/api/alerts";

/**
 * Price alerts that have fired but not yet been dismissed — the one widget on
 * the dashboard that is genuinely time-sensitive, so triggered alerts sort
 * ahead of everything and armed alerts are only summarised.
 */
export function AlertsWidget({ alerts }: { alerts: Alert[] | null }) {
  const all = alerts ?? [];
  const triggered = all.filter((alert) => alert.triggered_at && !alert.dismissed_at);
  const armed = all.filter((alert) => !alert.triggered_at && !alert.dismissed_at);

  return (
    <WidgetCard
      title="Alerts"
      titleId="dashboard-alerts-heading"
      action={{ label: "Manage", href: "/alerts" }}
    >
      {alerts === null ? (
        <WidgetEmpty>Alerts are unavailable right now.</WidgetEmpty>
      ) : triggered.length === 0 && armed.length === 0 ? (
        <WidgetEmpty>
          No alerts set.{" "}
          <Link href="/alerts" className="font-medium text-brand hover:underline">
            Watch a price
          </Link>
          .
        </WidgetEmpty>
      ) : (
        <div className="space-y-3">
          {triggered.slice(0, 3).map((alert) => (
            <Link
              key={alert.id}
              href={`/stocks/${encodeURIComponent(alert.ticker)}`}
              className="flex items-start gap-2.5 rounded-sm bg-warning-soft px-3 py-2.5 transition-opacity hover:opacity-90"
            >
              <BellRing
                className="mt-px size-3.5 shrink-0 text-warning-soft-foreground"
                aria-hidden
              />
              <span className="min-w-0 text-xs leading-5 text-warning-soft-foreground">
                <span className="font-mono font-semibold">{alert.ticker}</span> crossed{" "}
                {alert.direction} <span className="font-mono">{alert.target_price}</span>
              </span>
            </Link>
          ))}
          {armed.length > 0 ? (
            <p className="text-xs text-text-tertiary">
              {armed.length} alert{armed.length === 1 ? "" : "s"} armed and waiting.
            </p>
          ) : null}
        </div>
      )}
    </WidgetCard>
  );
}
