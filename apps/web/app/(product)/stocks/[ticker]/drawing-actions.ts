"use server";

/**
 * A3.2: the chart's drawings go through these server actions, so the
 * browser never holds the API token. Each returns `{ drawing }` or
 * `{ error }`; signed-out callers get "Sign in to save drawings".
 */

import { apiDetailMessage } from "@/lib/api-error-message";
import {
  type DrawingChanges,
  type DrawingInput,
  createDrawing,
  deleteDrawing,
  updateDrawing,
} from "@/lib/api/drawings";
import { AuthedApiError, UnauthenticatedError } from "@/lib/api/server";
import type { Drawing } from "@/lib/drawings/kinds";

export type DrawingActionResult = { drawing?: Drawing; ok?: boolean; error?: string };

async function run(work: () => Promise<DrawingActionResult>): Promise<DrawingActionResult> {
  try {
    return await work();
  } catch (err) {
    if (err instanceof UnauthenticatedError) return { error: "Sign in to save drawings" };
    if (err instanceof AuthedApiError) {
      return {
        error: apiDetailMessage(err.detail, `The drawing could not be saved (${err.status})`),
      };
    }
    return { error: "The drawing could not be saved. Try again." };
  }
}

export async function createDrawingAction(input: DrawingInput): Promise<DrawingActionResult> {
  return run(async () => ({ drawing: await createDrawing(input) }));
}

export async function updateDrawingAction(
  id: number,
  changes: DrawingChanges,
): Promise<DrawingActionResult> {
  return run(async () => ({ drawing: await updateDrawing(id, changes) }));
}

export async function deleteDrawingAction(id: number): Promise<DrawingActionResult> {
  return run(async () => {
    await deleteDrawing(id);
    return { ok: true };
  });
}
