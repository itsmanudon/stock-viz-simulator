/**
 * /alerts — in-app price alert management.
 *
 * Evaluated against stored daily closes when bars refresh. The header bell
 * remains a compact triggered indicator; this page is the system of record.
 */

import Link from "next/link";

import { AlertForm } from "@/components/alert-form";
import {
  AlertStatusBadge,
  MonitoringSubnav,
  OperationalEmptyState,
  OperationalPageHeader,
} from "@/components/operational-page-header";
import { PageFrame } from "@/components/page-frame";
import { getQuotes, listSymbols } from "@/lib/api";
import { type Alert, listAlerts } from "@/lib/api/alerts";
import {
  type AlertView,
  alertDirectionLabel,
  buildAlertsHref,
  currencyByTicker,
  formatNativePrice,
  parseAlertTicker,
  parseAlertView,
  tickerCurrency,
} from "@/lib/operational-trading";
import { cn } from "@/lib/utils";
import { deleteAlertAction, dismissAlertAction } from "./actions";

const VIEWS: { value: AlertView; label: string }[] = [
  { value: "active", label: "Active" },
  { value: "triggered", label: "Triggered" },
  { value: "all", label: "All" },
];

function fmtWhen(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function matchesView(alert: Alert, view: AlertView): boolean {
  if (view === "all") return true;
  if (view === "triggered") return Boolean(alert.triggered_at);
  return !alert.triggered_at;
}

export default async function AlertsPage({
  searchParams,
}: {
  searchParams: Promise<{ ticker?: string; view?: string }>;
}) {
  const params = await searchParams;
  const view = parseAlertView(params.view);
  const createTicker = parseAlertTicker(params.ticker);
  const [alerts, symbols] = await Promise.all([listAlerts(), listSymbols().catch(() => [])]);
  const currencies = currencyByTicker(symbols);
  const visible = alerts.filter((alert) => matchesView(alert, view));
  const quote = createTicker ? await getQuotes([createTicker]).catch(() => []) : [];

  return (
    <PageFrame width="workstation" className="py-6 sm:py-8">
      <OperationalPageHeader
        eyebrow="Portfolio"
        title="Alerts"
        description="In-app notifications when a stored daily close crosses a target. This is not email, push, or real-time exchange monitoring."
        meta={`${alerts.filter((alert) => !alert.triggered_at).length} active`}
      />
      <MonitoringSubnav current="/alerts" />

      <section
        aria-labelledby="create-alert-heading"
        className="mt-6 border-y border-border-muted sm:border-x"
      >
        <div className="border-b border-border-muted px-4 py-3">
          <h2 id="create-alert-heading" className="text-sm font-semibold">
            Create alert
          </h2>
        </div>
        <div className="max-w-md p-4">
          <AlertForm
            ticker={createTicker}
            lastClose={quote[0]?.close ?? null}
            currency={createTicker ? tickerCurrency(createTicker, currencies) : undefined}
            variant="inline"
          />
        </div>
      </section>

      <nav
        aria-label="Alert status"
        className="mt-8 flex flex-wrap gap-1 border-b border-border-muted"
      >
        {VIEWS.map((item) => {
          const active = item.value === view;
          return (
            <Link
              key={item.value}
              href={buildAlertsHref({ view: item.value, ticker: createTicker || undefined })}
              aria-current={active ? "page" : undefined}
              className={cn(
                "inline-flex h-10 items-center border-b-2 px-3 text-sm",
                active
                  ? "border-brand font-medium text-foreground"
                  : "border-transparent text-text-tertiary hover:text-foreground",
              )}
            >
              {item.label}
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
                ? "When a stored close crosses a target, the row moves here until you dismiss or delete it."
                : "Create a condition above, from a stock workspace, or from a watchlist row."}
            </p>
          </OperationalEmptyState>
        </div>
      ) : (
        <div className="mt-6 overflow-x-auto border-y border-border-muted">
          <table className="w-full min-w-[40rem] text-sm">
            <caption className="sr-only">Price alerts</caption>
            <thead>
              <tr className="border-b border-border-muted text-left text-[10px] font-semibold tracking-[0.12em] text-text-tertiary uppercase">
                <th scope="col" className="px-3 py-2.5">
                  Symbol
                </th>
                <th scope="col" className="px-3 py-2.5">
                  Condition
                </th>
                <th scope="col" className="px-3 py-2.5 text-right">
                  Target
                </th>
                <th scope="col" className="px-3 py-2.5">
                  Status
                </th>
                <th scope="col" className="hidden px-3 py-2.5 sm:table-cell">
                  Triggered
                </th>
                <th scope="col" className="px-3 py-2.5 text-right">
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {visible.map((alert) => (
                <tr key={alert.id} className="border-b border-border-muted last:border-0">
                  <td className="px-3 py-3 font-mono">
                    <Link href={`/stocks/${alert.ticker}`} className="hover:underline">
                      {alert.ticker}
                    </Link>
                  </td>
                  <td className="px-3 py-3 text-text-secondary">
                    {alertDirectionLabel(alert.direction)}
                  </td>
                  <td className="px-3 py-3 text-right font-mono">
                    {formatNativePrice(alert.target_price, alert.ticker, currencies)}
                  </td>
                  <td className="px-3 py-3">
                    <AlertStatusBadge
                      triggered={Boolean(alert.triggered_at)}
                      dismissed={Boolean(alert.dismissed_at)}
                    />
                  </td>
                  <td className="hidden px-3 py-3 text-text-tertiary sm:table-cell">
                    {fmtWhen(alert.triggered_at)}
                  </td>
                  <td className="px-3 py-3 text-right">
                    <div className="flex justify-end gap-2">
                      {alert.triggered_at && !alert.dismissed_at ? (
                        <form action={dismissAlertAction}>
                          <input type="hidden" name="id" value={alert.id} />
                          <button type="submit" className="text-xs hover:underline">
                            Dismiss
                          </button>
                        </form>
                      ) : null}
                      <form action={deleteAlertAction}>
                        <input type="hidden" name="id" value={alert.id} />
                        <button
                          type="submit"
                          className="text-xs text-text-tertiary hover:underline"
                        >
                          Delete
                        </button>
                      </form>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </PageFrame>
  );
}
