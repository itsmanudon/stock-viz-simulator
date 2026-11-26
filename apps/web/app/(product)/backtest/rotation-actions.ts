"use server";

/**
 * A4.4: the Rotation mode's run. Through the server so a watchlist and the
 * trial ledger belong to the signed-in user: authed when signed in, public
 * (with the visitor limit) otherwise, like the Rule strategy mode.
 */

import { auth } from "@/auth";
import { ApiError, apiPost } from "@/lib/api/client";
import { AuthedApiError, authedPost } from "@/lib/api/server";
import type { RotationRequest, RotationResult } from "@/lib/rotation";
import { describeRuleError } from "@/lib/screener-view";
import { checkVisitorLimit } from "@/lib/visitor-limit";

export type RotationRunState = { result?: RotationResult; error?: string; status?: number };

function detailOf(raw: string): string {
  const body = raw.replace(/^API \d+ [^:]+:\s*/, "");
  try {
    const parsed = JSON.parse(body) as { detail?: unknown };
    const detail = parsed.detail;
    if (typeof detail === "string") return detail;
    if (detail && typeof detail === "object" && "kind" in detail && "message" in detail) {
      return describeRuleError(detail as Parameters<typeof describeRuleError>[0]);
    }
    if (Array.isArray(detail)) {
      return detail
        .map((d) => (d && typeof d === "object" && "msg" in d ? String(d.msg) : String(d)))
        .join("; ");
    }
  } catch {
    // not JSON
  }
  return body || "The run failed.";
}

export async function runRotationAction(request: RotationRequest): Promise<RotationRunState> {
  try {
    const session = await auth();
    if (!session?.user?.id) {
      const limit = await checkVisitorLimit("strategy");
      if (!limit.allowed) {
        return {
          error: `Too many runs: try again in ${limit.retryAfterSeconds} seconds.`,
          status: 429,
        };
      }
    }
    const result = session?.user?.id
      ? await authedPost<RotationResult>("/v1/backtest/rotation", request)
      : await apiPost<RotationResult>("/v1/backtest/rotation", request, { maxAttempts: 1 });
    return { result };
  } catch (err) {
    if (err instanceof AuthedApiError) {
      return { error: detailOf(err.detail), status: err.status };
    }
    if (err instanceof ApiError) return { error: detailOf(err.message), status: err.status };
    return { error: "The run failed. Try again.", status: 500 };
  }
}
