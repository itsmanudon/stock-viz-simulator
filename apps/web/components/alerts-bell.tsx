"use client";

/**
 * Notification bell in the site header (Phase 7.3).
 *
 * Polls /api/notifications every 60 s for the unread count and the five
 * newest notifications. Audit RS-11: a failed poll keeps the last count (the
 * button's title says it could not refresh) instead of clearing the badge,
 * and polling stops while the tab is hidden and runs again when it returns.
 */

import { Bell } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { markAllNotificationsReadAction } from "@/app/(product)/(authed)/notifications/actions";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { formatUtcDateTime } from "@/lib/api-time";

export type BellNotification = {
  id: number;
  category: string;
  title: string;
  body: string;
  link: string | null;
  created_at: string;
  read_at: string | null;
};

type BellState = { unread: number; latest: BellNotification[]; stale: boolean };

export const POLL_INTERVAL_MS = 60_000;

async function fetchSummary(): Promise<{ unread: number; latest: BellNotification[] } | null> {
  try {
    const res = await fetch("/api/notifications", { cache: "no-store" });
    if (!res.ok) return null;
    const body = (await res.json()) as { unread?: number; latest?: BellNotification[] };
    return { unread: body.unread ?? 0, latest: body.latest ?? [] };
  } catch {
    return null;
  }
}

export function AlertsBell({ enabled }: { enabled: boolean }) {
  const [state, setState] = useState<BellState>({ unread: 0, latest: [], stale: false });
  const timer = useRef<number | null>(null);

  const tick = useCallback(async () => {
    const next = await fetchSummary();
    // RS-11: a failed poll keeps what we last knew and marks it stale.
    setState((prev) => (next ? { ...next, stale: false } : { ...prev, stale: true }));
  }, []);

  useEffect(() => {
    if (!enabled) return;
    const stop = () => {
      if (timer.current !== null) window.clearInterval(timer.current);
      timer.current = null;
    };
    const start = () => {
      stop();
      void tick();
      timer.current = window.setInterval(() => void tick(), POLL_INTERVAL_MS);
    };
    const onVisibility = () => (document.hidden ? stop() : start());
    if (!document.hidden) start();
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      stop();
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [enabled, tick]);

  if (!enabled) return null;

  const { unread, latest, stale } = state;
  const label =
    unread > 0 ? `${unread} unread notification${unread === 1 ? "" : "s"}` : "Notifications";

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        className="relative inline-flex h-9 w-9 items-center justify-center rounded-sm text-muted-foreground transition hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        aria-label={label}
        title={stale ? `${label} (couldn't refresh; showing the last count)` : label}
      >
        <Bell className="h-4 w-4" aria-hidden />
        {unread > 0 ? (
          <span
            data-testid="bell-count"
            className="absolute -right-0.5 -top-0.5 inline-flex h-4 min-w-[1rem] items-center justify-center rounded-full bg-negative px-1 text-3xs font-semibold leading-none text-white"
          >
            {unread > 9 ? "9+" : unread}
          </span>
        ) : null}
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-80">
        <DropdownMenuLabel>Notifications</DropdownMenuLabel>
        <DropdownMenuSeparator />
        {latest.length === 0 ? (
          <p className="px-2 py-3 text-xs text-muted-foreground">
            Nothing yet. Alerts, fills, dividends and splits show up here.
          </p>
        ) : (
          <ul className="max-h-80 overflow-y-auto">
            {latest.map((n) => (
              <li key={n.id} className="px-2 py-2 text-sm hover:bg-accent">
                <a href={n.link ?? "/notifications"} className="block">
                  <span className="flex items-center gap-2">
                    {n.read_at ? null : (
                      <span aria-hidden className="size-1.5 shrink-0 rounded-full bg-brand" />
                    )}
                    <span className="truncate font-medium">{n.title}</span>
                  </span>
                  <span className="mt-0.5 line-clamp-2 block text-xs text-muted-foreground">
                    {n.body}
                  </span>
                  <span className="mt-0.5 block text-3xs text-text-tertiary">
                    {formatUtcDateTime(n.created_at)}
                  </span>
                </a>
              </li>
            ))}
          </ul>
        )}
        <DropdownMenuSeparator />
        <div className="flex items-center justify-between px-2 py-2 text-xs">
          <a href="/notifications" className="text-foreground hover:underline">
            All notifications
          </a>
          {unread > 0 ? (
            <form action={markAllNotificationsReadAction} onSubmit={() => void tick()}>
              <button type="submit" className="text-muted-foreground hover:underline">
                Mark all read
              </button>
            </form>
          ) : null}
        </div>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
