import "server-only";

import { authedGet, authedPost } from "./server";

export type NotificationCategory =
  | "alert"
  | "order"
  | "dividend"
  | "corporate_action"
  | "option"
  | "system";

/** One in-app notification (Phase 7.2). */
export type AppNotification = {
  id: number;
  category: NotificationCategory | string;
  title: string;
  body: string;
  /** A path inside the app, or null. */
  link: string | null;
  created_at: string;
  read_at: string | null;
};

export function listNotifications(
  params: { category?: string; unread?: boolean; beforeId?: number; limit?: number } = {},
): Promise<AppNotification[]> {
  const q = new URLSearchParams();
  if (params.category) q.set("category", params.category);
  if (params.unread) q.set("unread", "true");
  if (params.beforeId) q.set("before_id", String(params.beforeId));
  q.set("limit", String(params.limit ?? 50));
  return authedGet<AppNotification[]>(`/v1/notifications?${q.toString()}`);
}

export async function unreadNotificationCount(): Promise<number> {
  const body = await authedGet<{ unread: number }>("/v1/notifications/unread-count");
  return body.unread;
}

export function markNotificationRead(id: number): Promise<AppNotification> {
  return authedPost<AppNotification>(`/v1/notifications/${id}/read`);
}

export function markAllNotificationsRead(): Promise<{ unread: number }> {
  return authedPost<{ unread: number }>("/v1/notifications/read-all");
}
