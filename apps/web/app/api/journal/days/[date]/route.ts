/**
 * Browser-callable view of the Journal day endpoint.
 *
 * The inspector fetches a day's executions only when that day is opened, which
 * is what keeps the month payload independent of trade volume.
 */

import { NextResponse } from "next/server";

import { auth } from "@/auth";
import { getJournalDay } from "@/lib/api/journal";
import { AuthedApiError, UnauthenticatedError } from "@/lib/api/server";
import { parseDateKey } from "@/lib/journal-view-model";

export async function GET(request: Request, { params }: { params: Promise<{ date: string }> }) {
  const session = await auth();
  if (!session?.user?.id) {
    return NextResponse.json({ error: "Not signed in" }, { status: 401 });
  }

  const { date } = await params;
  const offset = Number(new URL(request.url).searchParams.get("offset") ?? 0);
  if (!parseDateKey(date) || !Number.isSafeInteger(offset) || offset < 0) {
    return NextResponse.json({ error: "Invalid date" }, { status: 400 });
  }

  try {
    return NextResponse.json(await getJournalDay(date, offset), {
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
