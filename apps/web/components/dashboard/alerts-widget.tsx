import { Bell, BellRing } from "lucide-react";
import Link from "next/link";

import { WidgetCard, WidgetEmpty } from "@/components/dashboard/widget-card";
import type { Alert } from "@/lib/api/alerts";

/** Shown rows in all: fired alerts first, then armed ones (UI audit F3). */
const MAX_ROWS = 4;

function fmtTarget(raw: string): string {
  const value = Number(raw);
  return Number.isFinite(value)
    ? value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    : raw;
}

/**
 * Price alerts. Fired, undismissed alerts are the one time-sensitive thing on
 * the dashboard, so they come first; armed alerts follow as rows linked to
 * their symbol, rather than a count in an otherwise empty card.
 */
export function AlertsWidget({ alerts }: { alerts: Alert[] | null }) {
  const all = alerts ?? [];
  const triggered = all.filter((alert) => alert.triggered_at && !alert.dismissed_at);
  const armed = all.filter((alert) => !alert.triggered_at && !alert.dismissed_at);
  const shownTriggered = triggered.slice(0, MAX_ROWS);
  const shownArmed = armed.slice(0, MAX_ROWS - shownTriggered.length);
  const hidden = triggered.length + armed.length - shownTriggered.length - shownArmed.length;

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
          {shownTriggered.map((alert) => (
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
                {alert.direction} <span className="font-mono">{fmtTarget(alert.target_price)}</span>
              </span>
            </Link>
          ))}
          {shownArmed.length > 0 ? (
            <ul aria-label="Armed alerts" className="divide-y divide-border-muted">
              {shownArmed.map((alert) => (
                <li key={alert.id}>
                  <Link
                    href={`/stocks/${encodeURIComponent(alert.ticker)}`}
                    className="flex min-h-10 items-center gap-2.5 py-2 text-xs transition-colors hover:text-foreground"
                  >
                    <Bell className="size-3.5 shrink-0 text-text-tertiary" aria-hidden />
                    <span className="font-mono font-semibold">{alert.ticker}</span>
                    <span className="ml-auto text-text-secondary">
                      {alert.direction === "above" ? "Above" : "Below"}{" "}
                      <span className="font-mono" data-financial>
                        {fmtTarget(alert.target_price)}
                      </span>
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          ) : null}
          {hidden > 0 ? (
            <Link href="/alerts" className="block text-xs text-text-tertiary hover:underline">
              {hidden} more
            </Link>
          ) : null}
        </div>
      )}
    </WidgetCard>
  );
}
