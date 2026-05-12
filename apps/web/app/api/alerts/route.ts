/**
 * Browser-callable view of /v1/alerts.
 *
 * The browser can't hit the FastAPI service directly because the JWT bridge
 * is server-only. This route handler thinks of the NextAuth session as the
 * source of truth, mints the same Bearer token via ``listAlerts``, and
 * returns the JSON back to the polling client component.
 */

import { NextResponse } from "next/server";

import { auth } from "@/auth";
import { listAlerts } from "@/lib/api/alerts";
import { AuthedApiError, UnauthenticatedError } from "@/lib/api/server";

export async function GET() {
  const session = await auth();
  if (!session?.user?.id) {
    return NextResponse.json({ alerts: [] }, { status: 401 });
  }
  try {
    const alerts = await listAlerts();
    return NextResponse.json({ alerts });
  } catch (err) {
    if (err instanceof UnauthenticatedError) {
      return NextResponse.json({ alerts: [] }, { status: 401 });
    }
    if (err instanceof AuthedApiError) {
      return NextResponse.json({ alerts: [], error: err.detail }, { status: err.status });
    }
    throw err;
  }
}
