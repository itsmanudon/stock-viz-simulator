/**
 * Browser-callable preview of what a buy would do to the account's own
 * limits (Phase 8.5), for the order review. The JWT bridge is server-only.
 */

import { type NextRequest, NextResponse } from "next/server";

import { auth } from "@/auth";
import { AuthedApiError, UnauthenticatedError } from "@/lib/api/server";
import { previewLimits } from "@/lib/api/trading";

export async function GET(request: NextRequest) {
  const session = await auth();
  if (!session?.user?.id) {
    return NextResponse.json({ error: "unauthenticated" }, { status: 401 });
  }
  const ticker = request.nextUrl.searchParams.get("ticker")?.trim().toUpperCase() ?? "";
  const quantity = request.nextUrl.searchParams.get("quantity") ?? "";
  if (!/^[A-Z0-9.^-]{1,16}$/.test(ticker) || !(Number(quantity) > 0)) {
    return NextResponse.json(
      { error: "ticker and a positive quantity are required" },
      { status: 400 },
    );
  }
  try {
    return NextResponse.json(await previewLimits(ticker, quantity));
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
