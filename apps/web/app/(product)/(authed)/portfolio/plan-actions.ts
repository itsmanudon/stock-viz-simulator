"use server";

/**
 * Trade plans on the Journal tab (A5.4): edit, cancel, close, and plan an
 * open position (written after entry), through `/v1/plans`. The API holds
 * the lock: plan fields are refused with 409 after the first fill, and the
 * form shows its reason.
 */

import { revalidatePath } from "next/cache";

import { createPlan, updatePlan } from "@/lib/api/plans";
import { AuthedApiError, UnauthenticatedError } from "@/lib/api/server";
import { bookIdFromForm } from "@/lib/book-url";
import { type TradePlanPatch, planFigures, splitTags } from "@/lib/plans";

export type PlanActionState = { error?: string; ok?: string };

function message(err: unknown): PlanActionState {
  if (err instanceof UnauthenticatedError) return { error: "Sign in to manage plans" };
  if (err instanceof AuthedApiError) {
    try {
      const parsed = JSON.parse(err.detail) as { detail?: unknown };
      if (typeof parsed.detail === "string") return { error: parsed.detail };
      if (Array.isArray(parsed.detail)) {
        const first = parsed.detail[0] as { msg?: string } | undefined;
        if (first?.msg) return { error: first.msg.replace(/^Value error, /, "") };
      }
    } catch {
      // fall through
    }
    return { error: err.detail || `API ${err.status}` };
  }
  throw err;
}

function text(formData: FormData, name: string): string {
  return String(formData.get(name) ?? "").trim();
}

function refresh() {
  revalidatePath("/portfolio");
  revalidatePath("/trade");
}

export async function updatePlanAction(
  _prev: PlanActionState,
  formData: FormData,
): Promise<PlanActionState> {
  const id = Number(formData.get("plan_id"));
  if (!Number.isInteger(id) || id <= 0) return { error: "Unknown plan" };
  const body: TradePlanPatch = {
    notes: text(formData, "notes") || null,
    tags: splitTags(text(formData, "tags")),
  };
  // Plan fields are sent only while the form offers them (before any fill).
  if (formData.get("editable") === "1") {
    const form = {
      entry: text(formData, "entry"),
      stop: text(formData, "stop"),
      target: text(formData, "target"),
      size: text(formData, "size"),
    };
    const problem = planFigures(form).problem;
    if (problem) return { error: problem };
    body.planned_entry = form.entry;
    body.planned_stop = form.stop;
    body.planned_target = form.target || null;
    body.planned_size = form.size;
    body.why = text(formData, "why") || null;
  }
  const intent = formData.get("intent");
  if (intent === "cancel") body.status = "cancelled";
  if (intent === "close") body.status = "closed";
  try {
    await updatePlan(id, body);
  } catch (err) {
    return message(err);
  }
  refresh();
  return {
    ok: intent === "cancel" ? "Plan cancelled" : intent === "close" ? "Plan closed" : "Saved",
  };
}

export async function planOpenPositionAction(
  _prev: PlanActionState,
  formData: FormData,
): Promise<PlanActionState> {
  const ticker = text(formData, "ticker").toUpperCase();
  if (!ticker) return { error: "Choose a position" };
  const form = {
    entry: text(formData, "entry"),
    stop: text(formData, "stop"),
    target: text(formData, "target"),
    size: text(formData, "size"),
  };
  const problem = planFigures(form).problem;
  if (problem) return { error: problem };
  try {
    await createPlan(
      {
        ticker,
        side: "long",
        link_open_position: true,
        planned_entry: form.entry,
        planned_stop: form.stop,
        planned_target: form.target || null,
        planned_size: form.size,
        why: text(formData, "why") || null,
        tags: splitTags(text(formData, "tags")),
      },
      bookIdFromForm(formData),
    );
  } catch (err) {
    return message(err);
  }
  refresh();
  return { ok: `Plan saved for ${ticker}, labelled written after entry` };
}
