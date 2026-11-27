"use server";

import { apiDetail } from "@/lib/api-error-detail";
import type { AiProviderChoice, FigureExtraction } from "@/lib/api/ai";
import { extractFigures } from "@/lib/api/ai-server";
import { AuthedApiError, UnauthenticatedError } from "@/lib/api/server";

export type ExtractState = { result?: FigureExtraction; error?: string };

export async function extractFiguresAction(
  documentId: number,
  provider: AiProviderChoice,
): Promise<ExtractState> {
  try {
    return { result: await extractFigures(documentId, provider) };
  } catch (err) {
    if (err instanceof UnauthenticatedError) return { error: "Sign in to extract figures." };
    if (err instanceof AuthedApiError) {
      return { error: apiDetail(err.detail, "The figures could not be extracted just now.") };
    }
    return { error: "The figures could not be extracted just now." };
  }
}
