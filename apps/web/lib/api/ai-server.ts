import "server-only";

/** A8.2: plain English to a checked Rule DSL draft, as the signed-in user. */

import type { AiKey, AiKeys, AiProviderChoice, AiRule, CopilotAnswer } from "./ai";
import { authedDelete, authedGet, authedPost, authedPut } from "./server";

export function draftRule(text: string): Promise<AiRule> {
  return authedPost<AiRule>("/v1/ai/rule", { text, timeframe: "daily" });
}

/** A8.5: a question about stored documents, answered from cited passages. */
export function askCopilot(
  question: string,
  ticker?: string,
  provider: AiProviderChoice = "server",
): Promise<CopilotAnswer> {
  return authedPost<CopilotAnswer>("/v1/ai/ask", { question, ticker: ticker || null, provider });
}

/** A8.7: the caller's saved keys (never the key itself). */
export function listAiKeys(): Promise<AiKeys> {
  return authedGet<AiKeys>("/v1/ai/keys");
}

export function saveAiKey(
  provider: string,
  body: { api_key: string; model: string; base_url: string | null },
): Promise<AiKey> {
  return authedPut<AiKey>(`/v1/ai/keys/${encodeURIComponent(provider)}`, body);
}

export function deleteAiKey(provider: string): Promise<void> {
  return authedDelete(`/v1/ai/keys/${encodeURIComponent(provider)}`);
}
