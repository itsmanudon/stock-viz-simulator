"use server";

import { redirect } from "next/navigation";

import { apiDetail } from "@/lib/api-error-detail";
import {
  addAssignment,
  createCohort,
  joinCohort,
  leaveCohort,
  startAssignment,
} from "@/lib/api/classroom";
import { AuthedApiError } from "@/lib/api/server";

function back(message: string, kind: "ok" | "error" = "error"): never {
  redirect(`/classroom?${kind}=${encodeURIComponent(message.slice(0, 200))}`);
}

function failure(err: unknown, fallback: string): never {
  if (err instanceof AuthedApiError) back(apiDetail(err.detail, fallback));
  throw err;
}

export async function createCohortAction(formData: FormData): Promise<void> {
  const name = String(formData.get("name") ?? "").trim();
  if (!name) back("Give the cohort a name.");
  try {
    await createCohort(name);
  } catch (err) {
    failure(err, "The cohort could not be created.");
  }
  back(`Created ${name}.`, "ok");
}

export async function joinCohortAction(formData: FormData): Promise<void> {
  const code = String(formData.get("code") ?? "").trim();
  const consent = formData.get("consent") === "on";
  if (!consent) back("Tick the box to agree to what your instructor will see.");
  try {
    const cohort = await joinCohort(code, consent);
    back(`Joined ${cohort.name}.`, "ok");
  } catch (err) {
    failure(err, "That code did not work.");
  }
}

export async function leaveCohortAction(formData: FormData): Promise<void> {
  const id = Number(formData.get("cohort_id"));
  try {
    await leaveCohort(id);
  } catch (err) {
    failure(err, "Could not leave the cohort.");
  }
  back("You left the cohort.", "ok");
}

export async function addAssignmentAction(formData: FormData): Promise<void> {
  const id = Number(formData.get("cohort_id"));
  const tickers = String(formData.get("tickers") ?? "")
    .split(/[\s,]+/)
    .map((t) => t.trim().toUpperCase())
    .filter(Boolean)
    .slice(0, 50);
  const body = {
    title: String(formData.get("title") ?? "").trim(),
    min_followed_pct: Number(formData.get("min_followed_pct") ?? 70),
    due_on: String(formData.get("due_on") ?? "") || null,
    deck: {
      rule: { rule: String(formData.get("rule") ?? "").trim() },
      universe: { tickers },
      from: String(formData.get("from") ?? "") || null,
      to: String(formData.get("to") ?? "") || null,
      k: Number(formData.get("k") ?? 10),
      lead_bars: 60,
      follow_bars: 40,
      anonymised: true,
    },
  };
  if (!body.title || !body.deck.rule.rule || tickers.length === 0) {
    back("An assignment needs a title, a rule and at least one symbol.");
  }
  try {
    await addAssignment(id, body as Parameters<typeof addAssignment>[1]);
  } catch (err) {
    failure(err, "The assignment could not be created.");
  }
  back(`Assigned ${body.title}.`, "ok");
}

export async function startAssignmentAction(formData: FormData): Promise<void> {
  const id = Number(formData.get("assignment_id"));
  let deckId: number | null = null;
  try {
    deckId = (await startAssignment(id)).deck_id;
  } catch (err) {
    failure(err, "The assignment could not be started.");
  }
  redirect(`/drills?deck=${deckId}`);
}
