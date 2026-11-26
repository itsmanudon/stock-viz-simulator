"use server";

/**
 * A4.6: a replay session's own drawings go through these server actions
 * (`/v1/replay/sessions/{id}/drawings`), never the live chart's
 * `/v1/drawings`: a live drawing could sit on a later date and show the
 * future, so a session shows only the drawings made inside it.
 */

import { apiDetailMessage } from "@/lib/api-error-message";
import {
  type ReplayDrawingInput,
  createReplayDrawing,
  deleteReplayDrawing,
  updateReplayDrawing,
} from "@/lib/api/replay";
import { AuthedApiError, UnauthenticatedError } from "@/lib/api/server";
import type { Drawing } from "@/lib/drawings/kinds";

export type ReplayDrawingActionResult = { drawing?: Drawing; ok?: boolean; error?: string };

async function run(
  work: () => Promise<ReplayDrawingActionResult>,
): Promise<ReplayDrawingActionResult> {
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

export async function createReplayDrawingAction(
  sessionId: number,
  input: ReplayDrawingInput,
): Promise<ReplayDrawingActionResult> {
  return run(async () => ({ drawing: await createReplayDrawing(sessionId, input) }));
}

export async function updateReplayDrawingAction(
  sessionId: number,
  id: number,
  changes: Partial<Omit<ReplayDrawingInput, "kind">>,
): Promise<ReplayDrawingActionResult> {
  return run(async () => ({ drawing: await updateReplayDrawing(sessionId, id, changes) }));
}

export async function deleteReplayDrawingAction(
  sessionId: number,
  id: number,
): Promise<ReplayDrawingActionResult> {
  return run(async () => {
    await deleteReplayDrawing(sessionId, id);
    return { ok: true };
  });
}
