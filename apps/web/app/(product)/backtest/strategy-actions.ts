"use server";

/**
 * A4.1: the Rule strategy mode's server calls. A run goes through the server
 * so a watchlist, your own setup versions and rules that read your drawings
 * work: signed in it is an authed call, signed out a public one. The chart's
 * bars come through here too (public, cached).
 */

import { auth } from "@/auth";
import { getBars } from "@/lib/api/bars";
import { ApiError, apiPost } from "@/lib/api/client";
import { AuthedApiError, authedPost } from "@/lib/api/server";
import { createSetup } from "@/lib/api/setups-server";
import { getSymbol } from "@/lib/api/symbols";
import type { ApiInterval, Bar, IntradayInfo } from "@/lib/api/types";
import type { StrategyRequest, StrategyResult } from "@/lib/rule-strategy";
import { describeRuleError } from "@/lib/screener-view";
import { checkVisitorLimit } from "@/lib/visitor-limit";

export type StrategyRunState = { result?: StrategyResult; error?: string; status?: number };

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

export async function runStrategyAction(request: StrategyRequest): Promise<StrategyRunState> {
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
      ? await authedPost<StrategyResult>("/v1/backtest/strategy", request)
      : await apiPost<StrategyResult>("/v1/backtest/strategy", request, { maxAttempts: 1 });
    return { result };
  } catch (err) {
    if (err instanceof AuthedApiError) {
      return { error: detailOf(err.detail), status: err.status };
    }
    if (err instanceof ApiError) return { error: detailOf(err.message), status: err.status };
    return { error: "The run failed. Try again.", status: 500 };
  }
}

/**
 * Bars for the trades chart, from `from` to `to` (dates). A6.4: intraday bars
 * select by their open instant, so `to` reaches the end of its day.
 */
export async function strategyBarsAction(
  ticker: string,
  from: string,
  to: string,
  interval: ApiInterval = "1d",
): Promise<Bar[]> {
  try {
    if (interval === "1d") return await getBars(ticker, { from, to, limit: 5000 });
    return await getBars(ticker, { from, to: `${to}T23:59:59`, limit: 5000, interval });
  } catch {
    return [];
  }
}

/** A6.4: which intraday intervals a symbol has (null: daily only). */
export async function intradayInfoAction(ticker: string): Promise<IntradayInfo | null> {
  try {
    return (await getSymbol(ticker)).intraday ?? null;
  } catch {
    return null;
  }
}

export type SaveRuleState = { saved?: { id: number; name: string }; error?: string };

/** A6.4: save the entry rule as an alert setup on its timeframe (signed in). */
export async function saveRuleSetupAction(input: {
  name: string;
  rule: string;
  timeframe: NonNullable<StrategyRequest["timeframe"]>;
}): Promise<SaveRuleState> {
  const name = input.name.trim().slice(0, 120);
  if (!name) return { error: "Give the setup a name." };
  if (!input.rule.trim()) return { error: "Write a rule first." };
  try {
    const setup = await createSetup({
      name,
      rule: input.rule.trim(),
      kind: "alert",
      timeframe: input.timeframe,
    });
    return { saved: { id: setup.id, name: setup.name } };
  } catch (err) {
    if (err instanceof AuthedApiError && err.status === 422) {
      return { error: "The rule does not compile on this timeframe." };
    }
    if (err instanceof AuthedApiError && err.status === 409) return { error: err.message };
    return { error: "Sign in to save setups." };
  }
}
