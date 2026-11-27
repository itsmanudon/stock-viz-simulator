import "server-only";

/** A8.2: plain English to a checked Rule DSL draft, as the signed-in user. */

import type { AiRule } from "./ai";
import { authedPost } from "./server";

export function draftRule(text: string): Promise<AiRule> {
  return authedPost<AiRule>("/v1/ai/rule", { text, timeframe: "daily" });
}
