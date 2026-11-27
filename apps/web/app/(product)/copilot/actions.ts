"use server";

import { apiDetail } from "@/lib/api-error-detail";
import type { CopilotAnswer } from "@/lib/api/ai";
import { askCopilot } from "@/lib/api/ai-server";
import { AuthedApiError, UnauthenticatedError } from "@/lib/api/server";
import { questionProblem } from "@/lib/copilot";

export type CopilotState = { answer?: CopilotAnswer; error?: string };

export async function askCopilotAction(question: string, ticker: string): Promise<CopilotState> {
  const problem = questionProblem(question);
  if (problem) return { error: problem };
  const symbol = ticker.trim().toUpperCase().slice(0, 16);
  try {
    return { answer: await askCopilot(question.trim(), symbol || undefined) };
  } catch (err) {
    if (err instanceof UnauthenticatedError) return { error: "Sign in to ask the copilot." };
    if (err instanceof AuthedApiError) {
      if (err.status === 404) return { error: `${symbol} is not stored.` };
      return { error: apiDetail(err.detail, "The copilot could not answer just now.") };
    }
    return { error: "The copilot could not answer just now." };
  }
}
