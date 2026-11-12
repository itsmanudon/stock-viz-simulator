/**
 * Browser-callable summary of /v1/notifications for the header bell
 * (Phase 7.3): the unread count and the five newest notifications. The JWT
 * bridge is server-only, so the bell polls this instead of the API.
 */

import { NextResponse } from "next/server";

import { auth } from "@/auth";
import { listNotifications, unreadNotificationCount } from "@/lib/api/notifications";
import { AuthedApiError, UnauthenticatedError } from "@/lib/api/server";

export async function GET() {
  const session = await auth();
  if (!session?.user?.id) {
    return NextResponse.json({ error: "unauthenticated" }, { status: 401 });
  }
  try {
    const [unread, latest] = await Promise.all([
      unreadNotificationCount(),
      listNotifications({ limit: 5 }),
    ]);
    return NextResponse.json({ unread, latest });
  } catch (err) {
    if (err instanceof UnauthenticatedError) {
      return NextResponse.json({ error: "unauthenticated" }, { status: 401 });
    }
    if (err instanceof AuthedApiError) {
      return NextResponse.json({ error: err.detail }, { status: err.status });
    }
    throw err;
  }
}
