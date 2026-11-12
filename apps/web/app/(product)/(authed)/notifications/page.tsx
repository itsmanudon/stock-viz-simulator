/**
 * /notifications — the notification centre (Phase 7.3).
 *
 * Everything the account was told: alert firings, order fills, cancellations
 * and expiries, dividends, splits and option settlements, newest first, by
 * category. In-app only. Times are UTC and say so.
 */

import type { Metadata } from "next";
import Link from "next/link";

import { CountBadge } from "@/components/count-badge";
import {
  MonitoringSubnav,
  OperationalEmptyState,
  OperationalPageHeader,
} from "@/components/operational-page-header";
import { PageFrame } from "@/components/page-frame";
import { NOTIFICATION_CATEGORIES, parseNotificationCategory } from "@/lib/alert-rules";
import { formatUtcDateTime } from "@/lib/api-time";
import { listNotifications, unreadNotificationCount } from "@/lib/api/notifications";
import { cn } from "@/lib/utils";
import { markAllNotificationsReadAction, markNotificationReadAction } from "./actions";

export const metadata: Metadata = { title: "Notifications" };

const PAGE_SIZE = 50;

function href(category: string, beforeId?: number): string {
  const q = new URLSearchParams();
  if (category) q.set("category", category);
  if (beforeId) q.set("before", String(beforeId));
  const qs = q.toString();
  return qs ? `/notifications?${qs}` : "/notifications";
}

export default async function NotificationsPage({
  searchParams,
}: {
  searchParams: Promise<{ category?: string; before?: string }>;
}) {
  const params = await searchParams;
  const category = parseNotificationCategory(params.category);
  const before = Number(params.before);
  const beforeId = Number.isInteger(before) && before > 0 ? before : undefined;
  const [rows, unread] = await Promise.all([
    listNotifications({ category: category || undefined, beforeId, limit: PAGE_SIZE }),
    unreadNotificationCount().catch(() => 0),
  ]);
  const last = rows.at(-1);

  return (
    <PageFrame width="workstation" className="py-5 sm:py-7">
      <OperationalPageHeader
        eyebrow="Portfolio"
        title="Notifications"
        description="What happened to your account after each nightly run: alerts, fills, cancellations, dividends, splits and option settlements. In-app only."
        meta={<span>{unread} unread</span>}
      />
      <MonitoringSubnav current="/notifications" />

      <div className="mt-5 flex flex-wrap items-end justify-between gap-3 border-b border-border-muted">
        <nav aria-label="Notification category" className="flex flex-wrap gap-1">
          {NOTIFICATION_CATEGORIES.map((item) => {
            const active = item.value === category;
            return (
              <Link
                key={item.value || "all"}
                href={href(item.value)}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "inline-flex h-9 items-center border-b-2 px-2.5 text-sm",
                  active
                    ? "border-brand font-medium text-foreground"
                    : "border-transparent text-text-tertiary hover:text-foreground",
                )}
              >
                {item.label}
                {item.value === "" ? <CountBadge count={unread} /> : null}
              </Link>
            );
          })}
        </nav>
        {unread > 0 ? (
          <form action={markAllNotificationsReadAction} className="pb-1.5">
            <button type="submit" className="text-xs hover:underline">
              Mark all read
            </button>
          </form>
        ) : null}
      </div>

      {rows.length === 0 ? (
        <div className="mt-6">
          <OperationalEmptyState title={beforeId ? "No older notifications" : "No notifications"}>
            <p>
              Alerts you set, orders settled overnight, dividends and splits are reported here after
              each nightly run.
            </p>
          </OperationalEmptyState>
        </div>
      ) : (
        <ul
          aria-label="Notifications"
          className="mt-4 divide-y divide-border-muted rounded-md border border-border-muted bg-card"
        >
          {rows.map((n) => (
            <li key={n.id} className="flex items-start justify-between gap-4 px-4 py-3.5">
              <div className="min-w-0">
                <p className="flex items-center gap-2 text-sm font-medium">
                  {n.read_at ? null : (
                    <span className="size-1.5 shrink-0 rounded-full bg-brand">
                      <span className="sr-only">Unread</span>
                    </span>
                  )}
                  {n.link ? (
                    <Link href={n.link} className="hover:underline">
                      {n.title}
                    </Link>
                  ) : (
                    n.title
                  )}
                </p>
                <p className="mt-0.5 text-sm text-text-secondary">{n.body}</p>
                <p className="mt-1 text-2xs text-text-tertiary">
                  {formatUtcDateTime(n.created_at)} ·{" "}
                  {NOTIFICATION_CATEGORIES.find((c) => c.value === n.category)?.label ?? n.category}
                </p>
              </div>
              {n.read_at ? null : (
                <form action={markNotificationReadAction}>
                  <input type="hidden" name="id" value={n.id} />
                  <button type="submit" className="text-xs text-text-tertiary hover:underline">
                    Mark read
                  </button>
                </form>
              )}
            </li>
          ))}
        </ul>
      )}

      {rows.length === PAGE_SIZE && last ? (
        <p className="mt-4 text-sm">
          <Link href={href(category, last.id)} className="hover:underline">
            Older notifications
          </Link>
        </p>
      ) : null}
    </PageFrame>
  );
}
