/**
 * POST /api/revalidate — the nightly cron says the night's data is in (RS-9).
 *
 * Drops every market-data cache entry at once (`expire: 0`, so no visitor is
 * served the old night first), so a page never mixes bars from one night with
 * a close from the next. Authenticated by `x-stockviz-revalidate`.
 */

import { revalidateTag } from "next/cache";
import { NextResponse } from "next/server";

import { requireSecret } from "@/lib/env";
import { MARKET_TAGS, REVALIDATE_HEADER, isValidRevalidateKey } from "@/lib/revalidate-key";

export async function POST(request: Request) {
  const supplied = request.headers.get(REVALIDATE_HEADER);
  if (!isValidRevalidateKey(supplied, requireSecret("INTERNAL_API_TOKEN"))) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }
  for (const tag of MARKET_TAGS) {
    revalidateTag(tag, { expire: 0 });
  }
  return NextResponse.json({ revalidated: MARKET_TAGS });
}
