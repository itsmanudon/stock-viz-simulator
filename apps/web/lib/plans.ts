/**
 * Trade plans (A5.4, M10.3), client-safe: types, the ticket's plan draft,
 * its form fields and the risk figures the order review shows.
 *
 * A plan locks at its first fill (`locked`, `locked_at`); one written for a
 * position that was already open is `written_after_entry` and never shown as
 * locked. Once either, only notes and tags can change (`frozen`).
 */

import type { components } from "@/lib/api/schema";

export type TradePlan = components["schemas"]["TradePlanOut"];
export type TradePlans = components["schemas"]["TradePlansOut"];
export type TradePlanDraft = components["schemas"]["TradePlanDraft"];
export type TradePlanInput = components["schemas"]["TradePlanIn"];
export type TradePlanPatch = components["schemas"]["TradePlanPatch"];

/** A choice for the ticket's setup picker: one setup's newest version. */
export type PlanSetupOption = { versionId: number; label: string };
/** A choice for the ticket's thesis picker: an open thesis on a ticker. */
export type PlanThesisOption = { id: number; ticker: string | null; title: string };

/** The plan section's editable state on a ticket (strings, as typed). */
export type PlanFormState = {
  enabled: boolean;
  entry: string;
  stop: string;
  target: string;
  size: string;
  setupVersionId: string;
  thesisId: string;
  thesisText: string;
  why: string;
  tags: string;
};

export function emptyPlanForm(entry = "", size = ""): PlanFormState {
  return {
    enabled: false,
    entry,
    stop: "",
    target: "",
    size,
    setupVersionId: "",
    thesisId: "",
    thesisText: "",
    why: "",
    tags: "",
  };
}

export type PlanFigures = {
  riskPerShare: number | null;
  risk: number | null;
  reward: number | null;
  rewardRisk: number | null;
  /** Why the figures are missing or the plan is not valid, in plain words. */
  problem: string | null;
};

function num(value: string): number | null {
  if (value.trim() === "") return null;
  const n = Number(value);
  return Number.isFinite(n) && n > 0 ? n : null;
}

/** Risk, reward and R:R of a long plan, with the first problem found. */
export function planFigures(
  form: Pick<PlanFormState, "entry" | "stop" | "target" | "size">,
): PlanFigures {
  const entry = num(form.entry);
  const stop = num(form.stop);
  const target = num(form.target);
  const size = num(form.size);
  let problem: string | null = null;
  if (entry === null) problem = "Enter the planned entry";
  else if (stop === null) problem = "Enter the stop";
  else if (size === null) problem = "Enter the size";
  else if (stop >= entry) problem = "A long plan's stop must be below its entry";
  else if (form.target.trim() !== "" && (target === null || target <= entry))
    problem = "The target must be above the entry";
  const riskPerShare = entry !== null && stop !== null && stop < entry ? entry - stop : null;
  const risk = riskPerShare !== null && size !== null ? riskPerShare * size : null;
  const reward = target !== null && entry !== null && target > entry ? target - entry : null;
  const rewardRisk = reward !== null && riskPerShare ? reward / riskPerShare : null;
  return { riskPerShare, risk, reward, rewardRisk, problem };
}

export function splitTags(raw: string): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const part of raw.split(",")) {
    const tag = part.trim().replace(/\s+/g, " ").slice(0, 32);
    if (tag && !seen.has(tag.toLowerCase())) {
      seen.add(tag.toLowerCase());
      out.push(tag);
    }
  }
  return out.slice(0, 12);
}

/** The hidden fields a ticket posts for its plan (names read by `planFromForm`). */
export function planFormFields(form: PlanFormState): Record<string, string> {
  if (!form.enabled) return {};
  return {
    plan_enabled: "1",
    plan_entry: form.entry,
    plan_stop: form.stop,
    plan_target: form.target,
    plan_size: form.size,
    plan_setup_version_id: form.setupVersionId,
    plan_thesis_id: form.thesisId,
    plan_thesis_text: form.thesisText,
    plan_why: form.why,
    plan_tags: form.tags,
  };
}

/**
 * The plan a ticket posted, as the API's draft; null when the section was
 * off; `{ error }` when it does not make a plan.
 */
export function planFromForm(formData: FormData): TradePlanDraft | null | { error: string } {
  if (formData.get("plan_enabled") !== "1") return null;
  const text = (name: string) => String(formData.get(name) ?? "").trim();
  const form: PlanFormState = {
    enabled: true,
    entry: text("plan_entry"),
    stop: text("plan_stop"),
    target: text("plan_target"),
    size: text("plan_size"),
    setupVersionId: text("plan_setup_version_id"),
    thesisId: text("plan_thesis_id"),
    thesisText: text("plan_thesis_text"),
    why: text("plan_why"),
    tags: text("plan_tags"),
  };
  const figures = planFigures(form);
  if (figures.problem) return { error: `Plan: ${figures.problem}` };
  const id = (v: string) => (/^[1-9][0-9]*$/.test(v) ? Number(v) : null);
  return {
    side: "long",
    planned_entry: form.entry,
    planned_stop: form.stop,
    planned_target: form.target || null,
    planned_size: form.size,
    setup_version_id: id(form.setupVersionId),
    thesis_id: id(form.thesisId),
    thesis_text: form.thesisText || null,
    why: form.why || null,
    tags: splitTags(form.tags),
  };
}

export type PlanBadge = { label: string; tone: "locked" | "after" | "open" | "done" };

/** The badge a plan row shows: locked, written after entry, or its status. */
export function planBadge(
  plan: Pick<TradePlan, "locked" | "written_after_entry" | "status">,
): PlanBadge {
  if (plan.written_after_entry) return { label: "Written after entry", tone: "after" };
  if (plan.locked) return { label: "Locked", tone: "locked" };
  if (plan.status === "open") return { label: "Not filled yet", tone: "open" };
  return { label: plan.status === "cancelled" ? "Cancelled" : "Closed", tone: "done" };
}

export const PLAN_STATUS_LABEL: Record<TradePlan["status"], string> = {
  open: "Open",
  active: "Active",
  closed: "Closed",
  cancelled: "Cancelled",
};
