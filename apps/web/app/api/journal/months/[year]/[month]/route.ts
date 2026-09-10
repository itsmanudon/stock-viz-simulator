/**
 * Browser-callable view of the Journal month endpoint.
 *
 * Month navigation happens client-side so the calendar doesn't re-render the
 * whole portfolio page on every arrow press. The JWT bridge is server-only, so
 * the browser goes through here — the same shape as `app/api/alerts/route.ts`.
 */

import { NextResponse } from "next/server";

import { auth } from "@/auth";
import { getJournalMonth } from "@/lib/api/journal";
import { AuthedApiError, UnauthenticatedError } from "@/lib/api/server";

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ year: string; month: string }> },
) {
  const session = await auth();
  if (!session?.user?.id) {
    return NextResponse.json({ error: "Not signed in" }, { status: 401 });
  }

  const { year, month } = await params;
  const parsedYear = Number(year);
  const parsedMonth = Number(month);
  if (
    !Number.isInteger(parsedYear) ||
    parsedYear < 1970 ||
    parsedYear > 2200 ||
    !Number.isInteger(parsedMonth) ||
    parsedMonth < 1 ||
    parsedMonth > 12
  ) {
    return NextResponse.json({ error: "Invalid month" }, { status: 400 });
  }

  try {
    return NextResponse.json(await getJournalMonth(parsedYear, parsedMonth), {
      headers: { "Cache-Control": "private, no-store" },
    });
  } catch (err) {
    if (err instanceof UnauthenticatedError) {
      return NextResponse.json({ error: "Not signed in" }, { status: 401 });
    }
    if (err instanceof AuthedApiError) {
      return NextResponse.json({ error: err.detail }, { status: err.status });
    }
    throw err;
  }
}
