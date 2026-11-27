"use server";

import { apiDetail } from "@/lib/api-error-detail";
import type { AiProviderChoice, CopilotAnswer, Debate, ResearchGrid } from "@/lib/api/ai";
import { askCopilot, runDebate, runGrid } from "@/lib/api/ai-server";
import { AuthedApiError, UnauthenticatedError } from "@/lib/api/server";
import { questionProblem } from "@/lib/copilot";

export type CopilotState = { answer?: CopilotAnswer; error?: string };

export async function askCopilotAction(
  question: string,
  ticker: string,
  provider: AiProviderChoice = "server",
): Promise<CopilotState> {
  const problem = questionProblem(question);
  if (problem) return { error: problem };
  const symbol = ticker.trim().toUpperCase().slice(0, 16);
  try {
    return { answer: await askCopilot(question.trim(), symbol || undefined, provider) };
  } catch (err) {
    if (err instanceof UnauthenticatedError) return { error: "Sign in to ask the copilot." };
    if (err instanceof AuthedApiError) {
      if (err.status === 404) return { error: `${symbol} is not stored.` };
      return { error: apiDetail(err.detail, "The copilot could not answer just now.") };
    }
    return { error: "The copilot could not answer just now." };
  }
}

function failure(err: unknown, what: string): { error: string } {
  if (err instanceof UnauthenticatedError) return { error: "Sign in to use the copilot." };
  if (err instanceof AuthedApiError) {
    if (err.status === 404) return { error: "One of those symbols is not stored." };
    return { error: apiDetail(err.detail, `The ${what} could not be made just now.`) };
  }
  return { error: `The ${what} could not be made just now.` };
}

export type GridState = { grid?: ResearchGrid; error?: string };

export async function gridAction(
  tickers: string,
  questions: string[],
  provider: AiProviderChoice,
): Promise<GridState> {
  const list = tickers
    .split(/[\s,]+/)
    .map((t) => t.trim().toUpperCase())
    .filter(Boolean);
  const qs = questions.map((q) => q.trim()).filter(Boolean);
  if (list.length === 0 || list.length > 5) return { error: "Name one to five symbols." };
  if (qs.length === 0 || qs.some((q) => q.length < 5)) {
    return { error: "Ask one to three questions of at least five characters." };
  }
  try {
    return { grid: await runGrid(list, qs.slice(0, 3), provider) };
  } catch (err) {
    return failure(err, "grid");
  }
}

export type DebateState = { debate?: Debate; error?: string };

export async function debateAction(
  ticker: string,
  topic: string,
  provider: AiProviderChoice,
): Promise<DebateState> {
  const symbol = ticker.trim().toUpperCase();
  if (!symbol) return { error: "Name the symbol." };
  if (topic.trim().length < 5) return { error: "Give a topic of at least five characters." };
  try {
    return { debate: await runDebate(symbol, topic.trim(), provider) };
  } catch (err) {
    return failure(err, "cases");
  }
}
