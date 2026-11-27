import "server-only";

/** A8.2: plain English to a checked Rule DSL draft, as the signed-in user. */

import type { AiRule, CopilotAnswer } from "./ai";
import { authedPost } from "./server";

export function draftRule(text: string): Promise<AiRule> {
  return authedPost<AiRule>("/v1/ai/rule", { text, timeframe: "daily" });
}

/** A8.5: a question about stored documents, answered from cited passages. */
export function askCopilot(question: string, ticker?: string): Promise<CopilotAnswer> {
  return authedPost<CopilotAnswer>("/v1/ai/ask", { question, ticker: ticker || null });
}
