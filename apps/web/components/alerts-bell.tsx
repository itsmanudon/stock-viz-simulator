"use client";

/**
 * Notification bell in the site header.
 *
 * Polls /api/alerts every 60 s when the user is signed in. The badge count is
 * the number of triggered-but-undismissed alerts. Clicking it opens a
 * dropdown listing them, with dismiss / delete form-action buttons. The bell
 * silently hides for unauthenticated users.
 */

import { Bell } from "lucide-react";
import { useEffect, useState } from "react";

import { deleteAlertAction, dismissAlertAction } from "@/app/(authed)/alerts/actions";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

type Alert = {
  id: number;
  ticker: string;
  direction: "above" | "below";
  target_price: string;
  created_at: string;
  triggered_at: string | null;
  dismissed_at: string | null;
};

const POLL_INTERVAL_MS = 60_000;

async function fetchAlerts(): Promise<Alert[]> {
  const res = await fetch("/api/alerts", { cache: "no-store" });
  if (!res.ok) return [];
  const body = (await res.json()) as { alerts?: Alert[] };
  return body.alerts ?? [];
}

function fmtPrice(raw: string): string {
  return Number(raw).toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
  });
}

export function AlertsBell({ enabled }: { enabled: boolean }) {
  const [alerts, setAlerts] = useState<Alert[]>([]);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    const tick = async () => {
      const next = await fetchAlerts();
      if (!cancelled) setAlerts(next);
    };
    tick();
    const id = window.setInterval(tick, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [enabled]);

  if (!enabled) return null;

  const triggered = alerts.filter((a) => a.triggered_at && !a.dismissed_at);

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        className="relative inline-flex h-9 w-9 items-center justify-center rounded-sm text-muted-foreground transition hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        aria-label={
          triggered.length > 0
            ? `${triggered.length} unread alert${triggered.length === 1 ? "" : "s"}`
            : "Alerts"
        }
      >
        <Bell className="h-4 w-4" aria-hidden />
        {triggered.length > 0 ? (
          <span className="absolute -right-0.5 -top-0.5 inline-flex h-4 min-w-[1rem] items-center justify-center rounded-full bg-red-500 px-1 text-[10px] font-semibold leading-none text-white">
            {triggered.length > 9 ? "9+" : triggered.length}
          </span>
        ) : null}
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-80">
        <DropdownMenuLabel>Price alerts</DropdownMenuLabel>
        <DropdownMenuSeparator />
        {alerts.length === 0 ? (
          <p className="px-2 py-3 text-xs text-muted-foreground">
            No alerts yet. Set one from any stock page.
          </p>
        ) : (
          <ul className="max-h-80 overflow-y-auto">
            {alerts.map((alert) => {
              const isTriggered = Boolean(alert.triggered_at);
              const isDismissed = Boolean(alert.dismissed_at);
              return (
                <li
                  key={alert.id}
                  className="flex items-center justify-between gap-2 px-2 py-2 text-sm hover:bg-accent"
                >
                  <div>
                    <div className="font-mono font-semibold">{alert.ticker}</div>
                    <div className="text-xs text-muted-foreground">
                      {alert.direction === "above" ? "≥" : "≤"} {fmtPrice(alert.target_price)}
                    </div>
                    <div className="text-[10px] text-muted-foreground">
                      {isTriggered ? (isDismissed ? "Dismissed" : "Triggered") : "Pending"}
                    </div>
                  </div>
                  <div className="flex flex-col gap-1">
                    {isTriggered && !isDismissed ? (
                      <form action={dismissAlertAction}>
                        <input type="hidden" name="id" value={alert.id} />
                        <button
                          type="submit"
                          className="rounded-md border px-2 py-0.5 text-xs hover:bg-background"
                        >
                          Dismiss
                        </button>
                      </form>
                    ) : null}
                    <form action={deleteAlertAction}>
                      <input type="hidden" name="id" value={alert.id} />
                      <button
                        type="submit"
                        className="rounded-md border px-2 py-0.5 text-xs text-muted-foreground hover:bg-background"
                      >
                        Delete
                      </button>
                    </form>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
