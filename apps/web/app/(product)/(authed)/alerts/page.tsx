/**
 * /alerts — alert rules and their history (Phase 7.3, audit UX-3).
 *
 * Rules are judged on stored daily closes after each nightly run and fire
 * when their condition newly becomes true. Each row shows the rule in words,
 * the current close with its date, the distance to a price target, when it
 * last fired, and its actions (dismiss, re-arm, pause, delete). The history
 * below lists every firing with its bar date, value and threshold;
 * `?rule=<id>` narrows it to one rule. The header bell is the compact view.
 */

import type { Metadata } from "next";
import Link from "next/link";

import { AlertForm, type AlertSymbol } from "@/components/alert-form";
import { CountBadge } from "@/components/count-badge";
import {
  AlertStatusBadge,
  MonitoringSubnav,
  OperationalEmptyState,
  OperationalPageHeader,
} from "@/components/operational-page-header";
import { PageFrame } from "@/components/page-frame";
import { MetaChip } from "@/components/page-header";
import { StatusBadge } from "@/components/status-badge";
import { distanceToTargetPct, matchesAlertView } from "@/lib/alert-rules";
import { getMarketsSummary } from "@/lib/api";
import { formatUtcDateTime } from "@/lib/api-time";
import { type Alert, type AlertEvent, listAlertEvents, listAlerts } from "@/lib/api/alerts";
import {
  type AlertView,
  buildAlertsHref,
  parseAlertTicker,
  parseAlertView,
} from "@/lib/operational-trading";
import { formatCurrency } from "@/lib/portfolio-view-model";
import { formatCloseDate } from "@/lib/stock-workspace";
import { cn } from "@/lib/utils";
import {
  deleteAlertAction,
  dismissAlertAction,
  rearmAlertAction,
  toggleAlertPausedAction,
} from "./actions";

export const metadata: Metadata = { title: "Alerts" };

const VIEWS: { value: AlertView; label: string }[] = [
  { value: "active", label: "Active" },
  { value: "triggered", label: "Triggered" },
  { value: "all", label: "All" },
];

function Action({
  action,
  id,
  label,
  extra,
  muted,
}: {
  action: (formData: FormData) => Promise<void>;
  id: number;
  label: string;
  extra?: Record<string, string>;
  muted?: boolean;
}) {
  return (
    <form action={action}>
      <input type="hidden" name="id" value={id} />
      {Object.entries(extra ?? {}).map(([k, v]) => (
        <input key={k} type="hidden" name={k} value={v} />
      ))}
      <button
        type="submit"
        className={cn("text-xs hover:underline", muted && "text-text-tertiary")}
      >
        {label}
      </button>
    </form>
  );
}

function AlertActions({ alert }: { alert: Alert }) {
  const fired = Boolean(alert.triggered_at);
  return (
    <div className="flex flex-wrap justify-end gap-3">
      {fired && !alert.dismissed_at ? (
        <Action action={dismissAlertAction} id={alert.id} label="Dismiss" />
      ) : null}
      {fired && alert.repeat !== "every_cross" ? (
        <Action action={rearmAlertAction} id={alert.id} label="Re-arm" />
      ) : null}
      <Action
        action={toggleAlertPausedAction}
        id={alert.id}
        label={alert.paused ? "Resume" : "Pause"}
        extra={{ paused: alert.paused ? "false" : "true" }}
      />
      <Link href={`/alerts?rule=${alert.id}#history`} className="text-xs hover:underline">
        History
      </Link>
      <Action action={deleteAlertAction} id={alert.id} label="Delete" muted />
    </div>
  );
}

function RuleStatus({ alert }: { alert: Alert }) {
  if (alert.paused) return <StatusBadge label="Paused" tone="neutral" />;
  return (
    <AlertStatusBadge
      triggered={Boolean(alert.triggered_at)}
      dismissed={Boolean(alert.dismissed_at)}
    />
  );
}

function describe(alert: Alert): string {
  if (alert.description) return alert.description;
  return `${alert.ticker} closes ${alert.direction ?? "above"} ${alert.target_price ?? ""}`;
}

export default async function AlertsPage({
  searchParams,
}: {
  searchParams: Promise<{ ticker?: string; view?: string; rule?: string }>;
}) {
  const params = await searchParams;
  const view = parseAlertView(params.view);
  const createTicker = parseAlertTicker(params.ticker);
  const ruleId = Number(params.rule);
  const [alerts, summary, events] = await Promise.all([
    listAlerts(),
    getMarketsSummary().catch(() => ({ rows: [], sectors: [] })),
    listAlertEvents(100).catch(() => [] as AlertEvent[]),
  ]);
  const rows = new Map(summary.rows.map((r) => [r.ticker, r]));
  const symbols: AlertSymbol[] = summary.rows.map((r) => ({
    ticker: r.ticker,
    name: r.name,
    currency: r.currency,
    last_close: r.last_close,
    last_close_at: r.last_close_at,
  }));
  const visible = alerts.filter((alert) => matchesAlertView(alert, view));
  // Tab counts use the same rule as the list, so a tab never claims rows it
  // would not show.
  const counts = Object.fromEntries(
    VIEWS.map((item) => [
      item.value,
      alerts.filter((alert) => matchesAlertView(alert, item.value)).length,
    ]),
  ) as Record<AlertView, number>;
  const rule = Number.isInteger(ruleId) ? alerts.find((a) => a.id === ruleId) : undefined;
  const history = rule ? events.filter((e) => e.alert_id === rule.id) : events;
  const created = createTicker ? rows.get(createTicker) : undefined;

  return (
    <PageFrame width="workstation" className="py-5 sm:py-7">
      <OperationalPageHeader
        eyebrow="Portfolio"
        title="Alerts"
        description="Rules on prices, indicators, Aegis news and your portfolio, judged on stored daily closes after each nightly run. In-app notifications, not real-time monitoring."
        meta={
          <span className="flex flex-wrap items-center gap-2">
            <span>{counts.active} active</span>
            <MetaChip>Checked after each weekday close</MetaChip>
          </span>
        }
      />
      <MonitoringSubnav current="/alerts" />

      <section
        aria-labelledby="create-alert-heading"
        className="mt-5 overflow-hidden rounded-md border border-border-muted bg-card"
      >
        <div className="border-b border-border-muted px-4 py-3.5">
          <h2 id="create-alert-heading" className="text-sm font-semibold">
            Create alert
          </h2>
        </div>
        <div className="max-w-md p-4">
          <AlertForm
            ticker={createTicker}
            lastClose={created?.last_close ?? null}
            lastCloseAt={created?.last_close_at ?? null}
            currency={created?.currency}
            symbols={symbols}
            variant="inline"
          />
        </div>
      </section>

      <nav
        aria-label="Alert status"
        className="mt-7 flex flex-wrap gap-1 border-b border-border-muted"
      >
        {VIEWS.map((item) => {
          const active = item.value === view;
          return (
            <Link
              key={item.value}
              href={buildAlertsHref({ view: item.value, ticker: createTicker || undefined })}
              aria-current={active ? "page" : undefined}
              className={cn(
                "inline-flex h-9 items-center border-b-2 px-2.5 text-sm",
                active
                  ? "border-brand font-medium text-foreground"
                  : "border-transparent text-text-tertiary hover:text-foreground",
              )}
            >
              {item.label}
              <CountBadge count={counts[item.value]} />
            </Link>
          );
        })}
      </nav>

      {visible.length === 0 ? (
        <div className="mt-6">
          <OperationalEmptyState
            title={
              view === "triggered"
                ? "No triggered alerts"
                : view === "all"
                  ? "No alerts yet"
                  : "No active alerts"
            }
            action={
              <Link href="/watchlist" className="text-sm hover:underline">
                Monitor a watchlist symbol
              </Link>
            }
          >
            <p>
              {view === "triggered"
                ? "When a rule fires, it shows here until you dismiss or delete it."
                : "Create a rule above, from a stock workspace, or from a watchlist row."}
            </p>
          </OperationalEmptyState>
        </div>
      ) : (
        <ul aria-label="Alert rules" className="mt-5 grid gap-3">
          {visible.map((alert) => {
            const row = alert.ticker ? rows.get(alert.ticker) : undefined;
            const currency = alert.currency ?? row?.currency ?? "USD";
            const distance =
              alert.target_price !== null
                ? distanceToTargetPct(row?.last_close, alert.target_price)
                : null;
            return (
              <li
                key={alert.id}
                className={cn(
                  "grid gap-3 rounded-md border border-border-muted bg-card p-4 md:grid-cols-[minmax(0,2fr)_minmax(0,1fr)_minmax(0,1fr)_auto] md:items-center",
                  rule?.id === alert.id && "border-brand",
                )}
              >
                <div className="min-w-0">
                  <p className="text-sm font-medium">
                    {alert.ticker ? (
                      <Link
                        href={`/stocks/${alert.ticker}`}
                        className="ticker mr-2 font-semibold hover:underline"
                      >
                        {alert.ticker}
                      </Link>
                    ) : null}
                    <span className="text-text-secondary">{describe(alert)}</span>
                  </p>
                  <p className="mt-0.5 text-2xs text-text-tertiary">
                    {alert.kind ?? "price"} ·{" "}
                    {alert.repeat === "every_cross" ? "every cross" : "once"}
                    {alert.last_bar_date
                      ? ` · judged on ${alert.last_bar_date}`
                      : " · not judged yet"}
                  </p>
                </div>
                <div className="text-xs">
                  {row?.last_close ? (
                    <>
                      <span className="font-mono" data-financial>
                        {formatCurrency(row.last_close, currency)}
                      </span>
                      {row.last_close_at ? (
                        <span className="text-text-tertiary">
                          {" "}
                          on {formatCloseDate(row.last_close_at)}
                        </span>
                      ) : null}
                      {distance !== null ? (
                        <span className="block text-text-tertiary">
                          Target {Math.abs(distance).toFixed(2)}%{" "}
                          {distance >= 0 ? "above" : "below"}
                        </span>
                      ) : null}
                    </>
                  ) : (
                    <span className="text-text-tertiary">
                      {alert.ticker ? "No stored close" : "Whole account"}
                    </span>
                  )}
                </div>
                <div className="flex flex-col items-start gap-1 text-xs">
                  <RuleStatus alert={alert} />
                  <span className="text-text-tertiary">
                    {alert.last_fired_bar_date
                      ? `Last fired on the ${alert.last_fired_bar_date} close`
                      : alert.triggered_at
                        ? `Fired ${formatUtcDateTime(alert.triggered_at)}`
                        : "Not fired"}
                  </span>
                </div>
                <AlertActions alert={alert} />
              </li>
            );
          })}
        </ul>
      )}

      <section id="history" aria-labelledby="history-heading" className="mt-8">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 id="history-heading" className="text-sm font-semibold">
            {rule ? `History: ${describe(rule)}` : "Recent firings"}
          </h2>
          {rule ? (
            <Link href="/alerts#history" className="text-xs hover:underline">
              All rules
            </Link>
          ) : null}
        </div>
        {history.length === 0 ? (
          <p className="mt-2 text-sm text-text-tertiary">Nothing has fired yet.</p>
        ) : (
          <ol className="mt-3 divide-y divide-border-muted rounded-md border border-border-muted bg-card">
            {history.map((e) => (
              <li key={e.id} className="px-4 py-3 text-sm">
                <p>{e.message}</p>
                <p className="mt-0.5 text-2xs text-text-tertiary">
                  {e.bar_date ? `Bar ${e.bar_date} · ` : ""}session {e.session_date} · recorded{" "}
                  {formatUtcDateTime(e.created_at)}
                </p>
              </li>
            ))}
          </ol>
        )}
      </section>
    </PageFrame>
  );
}
