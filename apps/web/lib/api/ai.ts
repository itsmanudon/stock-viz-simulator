/** A8.2 / A8.3: whether the server has a model (public, cached a minute). */

import { apiGet } from "./client";
import type { components } from "./schema";

export type AiStatus = components["schemas"]["AiStatusOut"];
export type AiRule = components["schemas"]["AiRuleOut"];
export type CopilotAnswer = components["schemas"]["AskOut"];
export type CopilotSource = components["schemas"]["AskSourceOut"];
export type AiKeys = components["schemas"]["AiKeysOut"];
export type AiKey = components["schemas"]["AiKeyOut"];
export type AiProviderChoice = "server" | "openai_compatible";
export type FigureExtraction = components["schemas"]["ExtractOut"];

export function getAiStatus(): Promise<AiStatus> {
  return apiGet<AiStatus>("/v1/ai/status", { revalidateSeconds: 60, tags: ["ai"] });
}
