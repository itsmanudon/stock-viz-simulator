"use server";

/**
 * A6.8 (M2.10): save and delete chart layouts and templates, over
 * `lib/api/chart-layouts.ts`. The workspace (`/charts`) and the stock page's
 * "Save as template" call these.
 */

import { revalidatePath } from "next/cache";

import { apiDetailMessage } from "@/lib/api-error-message";
import {
  type ChartLayoutInput,
  type ChartTemplateInput,
  createChartLayout,
  createChartTemplate,
  deleteChartLayout,
  deleteChartTemplate,
  updateChartLayout,
} from "@/lib/api/chart-layouts";
import { AuthedApiError, UnauthenticatedError } from "@/lib/api/server";

export type ChartActionResult = { ok?: boolean; id?: number; error?: string };

function failure(err: unknown, fallback: string): ChartActionResult {
  if (err instanceof UnauthenticatedError) return { error: "Sign in to save charts." };
  if (err instanceof AuthedApiError) return { error: apiDetailMessage(err.detail, fallback) };
  throw err;
}

/** Saves the workspace as a new layout, or over `layoutId`. */
export async function saveLayoutAction(
  layoutId: number | null,
  body: ChartLayoutInput,
): Promise<ChartActionResult> {
  try {
    const saved = layoutId
      ? await updateChartLayout(layoutId, body)
      : await createChartLayout(body);
    revalidatePath("/charts");
    return { ok: true, id: saved.id };
  } catch (err) {
    return failure(err, "The layout could not be saved.");
  }
}

export async function deleteLayoutAction(layoutId: number): Promise<ChartActionResult> {
  try {
    await deleteChartLayout(layoutId);
  } catch (err) {
    return failure(err, "The layout could not be deleted.");
  }
  revalidatePath("/charts");
  return { ok: true };
}

export async function createTemplateAction(body: ChartTemplateInput): Promise<ChartActionResult> {
  try {
    const saved = await createChartTemplate(body);
    revalidatePath("/charts");
    return { ok: true, id: saved.id };
  } catch (err) {
    return failure(err, "The template could not be saved.");
  }
}

export async function deleteTemplateAction(templateId: number): Promise<ChartActionResult> {
  try {
    await deleteChartTemplate(templateId);
  } catch (err) {
    return failure(err, "The template could not be deleted.");
  }
  revalidatePath("/charts");
  return { ok: true };
}
