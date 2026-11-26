/**
 * POST /v1/rules/check (A2.2): validate a Rule DSL rule. Public and
 * browser-safe (the API limits it to 60 a minute per visitor), so the
 * screener's rule editor calls it as the user types, debounced. Always 200:
 * the canonical form, or the error with its line and column.
 */

import { apiPost } from "./client";
import type { components } from "./schema";

export type RuleCheck = components["schemas"]["RuleCheckOut"];
export type RuleCheckError = components["schemas"]["RuleErrorOut"];

/** A6.4: the bars a rule is judged on. */
export type RuleTimeframe = NonNullable<components["schemas"]["RuleCheckIn"]["timeframe"]>;

export function checkRule(
  rule: string,
  signal?: AbortSignal,
  expect: "condition" | "number" = "condition",
  timeframe: RuleTimeframe = "daily",
): Promise<RuleCheck> {
  const body: Record<string, string> = { rule };
  if (expect === "number") body.expect = expect;
  // A6.4: daily is the default; an intraday timeframe checks daily. and the
  // per-binding rules, with the warm-up counted in that timeframe's bars.
  if (timeframe !== "daily") body.timeframe = timeframe;
  return apiPost<RuleCheck>("/v1/rules/check", body, { init: { signal }, maxAttempts: 1 });
}

/** A4.4: check a numeric expression (a rotation's ranking), not a condition. */
export function checkNumber(rule: string, signal?: AbortSignal): Promise<RuleCheck> {
  return checkRule(rule, signal, "number");
}
