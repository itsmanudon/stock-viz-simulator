"use server";

/**
 * A4.3: the one-time holdout unlock and the template run, through the
 * server so the trial ledger and the unlock belong to the signed-in user.
 */

import { auth } from "@/auth";
import { ApiError, apiPost } from "@/lib/api/client";
import { AuthedApiError, authedPost } from "@/lib/api/server";
import type { BacktestRequest, BacktestResult } from "@/lib/api/types";
import type { OverfittingChecks } from "@/lib/report-card";
import type { RotationRequest } from "@/lib/rotation";
import type { StrategyRequest } from "@/lib/rule-strategy";
import { checkVisitorLimit } from "@/lib/visitor-limit";

export type UnlockState = { checks?: OverfittingChecks; error?: string };
export type TemplateRunState = { result?: BacktestResult; error?: string; status?: number };

function detail(raw: string): string {
  const body = raw.replace(/^API \d+ [^:]+:\s*/, "");
  try {
    const parsed = JSON.parse(body) as { detail?: unknown };
    if (typeof parsed.detail === "string") return parsed.detail;
  } catch {
    // plain text
  }
  return body || "The request failed.";
}

export async function unlockHoldoutAction(payload: {
  backtest?: BacktestRequest;
  strategy?: StrategyRequest;
  rotation?: RotationRequest;
}): Promise<UnlockState> {
  const session = await auth();
  if (!session?.user?.id) return { error: "Sign in to unlock the holdout." };
  try {
    const checks = await authedPost<OverfittingChecks>("/v1/backtest/holdout/unlock", payload);
    return { checks };
  } catch (err) {
    if (err instanceof AuthedApiError) return { error: detail(err.detail) };
    return { error: "The holdout could not be unlocked. Try again." };
  }
}

/** A template run: authed when signed in (your trial ledger), else public. */
export async function runTemplateAction(request: BacktestRequest): Promise<TemplateRunState> {
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
      return {
        result: await apiPost<BacktestResult>("/v1/backtest", request, { maxAttempts: 1 }),
      };
    }
    return { result: await authedPost<BacktestResult>("/v1/backtest", request) };
  } catch (err) {
    if (err instanceof AuthedApiError) return { error: detail(err.detail), status: err.status };
    if (err instanceof ApiError) return { error: detail(err.message), status: err.status };
    return { error: "Backtest failed", status: 500 };
  }
}
