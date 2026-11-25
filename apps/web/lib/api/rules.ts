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

export function checkRule(rule: string, signal?: AbortSignal): Promise<RuleCheck> {
  return apiPost<RuleCheck>("/v1/rules/check", { rule }, { init: { signal }, maxAttempts: 1 });
}
