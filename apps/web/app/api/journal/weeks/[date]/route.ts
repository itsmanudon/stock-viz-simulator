import { NextResponse } from "next/server";

import { auth } from "@/auth";
import { getJournalWeek } from "@/lib/api/journal";
import { AuthedApiError, UnauthenticatedError } from "@/lib/api/server";
import { parseDateKey } from "@/lib/journal-view-model";

export async function GET(_request: Request, { params }: { params: Promise<{ date: string }> }) {
  const session = await auth();
  if (!session?.user?.id) return NextResponse.json({ error: "Not signed in" }, { status: 401 });
  const { date } = await params;
  if (!parseDateKey(date)) return NextResponse.json({ error: "Invalid date" }, { status: 400 });
  try {
    return NextResponse.json(await getJournalWeek(date), {
      headers: { "Cache-Control": "private, no-store" },
    });
  } catch (err) {
    if (err instanceof UnauthenticatedError)
      return NextResponse.json({ error: "Not signed in" }, { status: 401 });
    if (err instanceof AuthedApiError)
      return NextResponse.json({ error: err.detail }, { status: err.status });
    throw err;
  }
}
