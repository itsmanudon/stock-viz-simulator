"use server";

/**
 * A4.7: drill decks, plans, reveal and a drill's drawings, over
 * `lib/api/drills.ts` (`/v1/drills`). Orders and stepping go through the
 * replay actions with `target=drill` (`replay/actions.ts`).
 */

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import { apiDetailMessage } from "@/lib/api-error-message";
import {
  createDrillDeck,
  createDrillDrawing,
  deleteDrillDeck,
  deleteDrillDrawing,
  putDrillPlan,
  revealDrill,
  updateDrillDrawing,
} from "@/lib/api/drills";
import type { ReplayDrawingInput } from "@/lib/api/replay";
import { AuthedApiError, UnauthenticatedError } from "@/lib/api/server";
import type { Drawing } from "@/lib/drawings/kinds";
import type { DrillDeckRequest } from "@/lib/drills";

export type DrillActionState = { error?: string; ok?: boolean };

function message(err: unknown, fallback: string): DrillActionState {
  if (err instanceof UnauthenticatedError) return { error: "Sign in to use drills." };
  if (err instanceof AuthedApiError) {
    if (err.status === 422) {
      try {
        const parsed = JSON.parse(err.detail) as { detail?: { message?: string } };
        if (parsed.detail && typeof parsed.detail === "object" && parsed.detail.message) {
          return { error: `The rule does not compile: ${parsed.detail.message}` };
        }
      } catch {
        // not a rule error
      }
    }
    return { error: apiDetailMessage(err.detail, fallback) };
  }
  throw err;
}

export async function createDeckAction(body: DrillDeckRequest): Promise<DrillActionState> {
  let deckId: number;
  try {
    const deck = await createDrillDeck(body);
    deckId = deck.id;
  } catch (err) {
    return message(err, "The deck could not be created.");
  }
  revalidatePath("/drills");
  redirect(`/drills?deck=${deckId}`);
}

export async function deleteDeckAction(
  _prev: DrillActionState,
  formData: FormData,
): Promise<DrillActionState> {
  const deckId = Number(formData.get("deck_id"));
  if (!Number.isInteger(deckId) || deckId <= 0) return { error: "Invalid deck." };
  try {
    await deleteDrillDeck(deckId);
  } catch (err) {
    return message(err, "The deck could not be deleted.");
  }
  revalidatePath("/drills");
  return { ok: true };
}

export async function savePlanAction(
  _prev: DrillActionState,
  formData: FormData,
): Promise<DrillActionState> {
  const drillId = Number(formData.get("drill_id"));
  const entry = String(formData.get("planned_entry") ?? "").trim();
  const stop = String(formData.get("planned_stop") ?? "").trim();
  const size = String(formData.get("planned_size") ?? "").trim();
  const note = String(formData.get("note") ?? "").trim();
  if (!Number.isInteger(drillId) || drillId <= 0) return { error: "Invalid drill." };
  if (!(Number(entry) > 0) || !(Number(stop) > 0) || !(Number(size) > 0)) {
    return { error: "Entry, stop and size must be positive numbers." };
  }
  if (Number(stop) >= Number(entry)) return { error: "A long plan's stop is below its entry." };
  try {
    await putDrillPlan(drillId, {
      planned_entry: entry,
      planned_stop: stop,
      planned_size: size,
      note: note || null,
    });
  } catch (err) {
    return message(err, "The plan could not be saved.");
  }
  revalidatePath(`/drills/${drillId}`);
  return { ok: true };
}

export async function revealDrillAction(
  _prev: DrillActionState,
  formData: FormData,
): Promise<DrillActionState> {
  const drillId = Number(formData.get("drill_id"));
  if (!Number.isInteger(drillId) || drillId <= 0) return { error: "Invalid drill." };
  try {
    await revealDrill(drillId);
  } catch (err) {
    return message(err, "The drill could not be revealed.");
  }
  revalidatePath(`/drills/${drillId}`);
  revalidatePath("/drills");
  return { ok: true };
}

export type DrillDrawingResult = { drawing?: Drawing; ok?: boolean; error?: string };

async function drawing(work: () => Promise<DrillDrawingResult>): Promise<DrillDrawingResult> {
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

export async function createDrillDrawingAction(
  drillId: number,
  input: ReplayDrawingInput,
): Promise<DrillDrawingResult> {
  return drawing(async () => ({ drawing: await createDrillDrawing(drillId, input) }));
}

export async function updateDrillDrawingAction(
  drillId: number,
  id: number,
  changes: Partial<Omit<ReplayDrawingInput, "kind">>,
): Promise<DrillDrawingResult> {
  return drawing(async () => ({ drawing: await updateDrillDrawing(drillId, id, changes) }));
}

export async function deleteDrillDrawingAction(
  drillId: number,
  id: number,
): Promise<DrillDrawingResult> {
  return drawing(async () => {
    await deleteDrillDrawing(drillId, id);
    return { ok: true };
  });
}
