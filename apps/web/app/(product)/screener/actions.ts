"use server";

import { revalidatePath } from "next/cache";

import { apiDetail } from "@/lib/api-error-detail";
import { draftRule } from "@/lib/api/ai-server";
import { checkRule } from "@/lib/api/rules";
import {
  type SavedScreen,
  deleteScreen,
  listSavedScreens,
  saveScreen,
  setScreenNotify,
} from "@/lib/api/screens";
import { AuthedApiError, UnauthenticatedError } from "@/lib/api/server";
import { createSetup, forkSetup, listSetups } from "@/lib/api/setups-server";

function ruleOf(query: string): string {
  return (new URLSearchParams(query).get("rule") ?? "").trim();
}

export type ScreenActionState = { saved?: string; error?: string };

/** Save the screen on show under a name (Phase 6.2). Same name replaces it. */
export async function saveScreenAction(
  _prev: ScreenActionState,
  formData: FormData,
): Promise<ScreenActionState> {
  const name = String(formData.get("name") ?? "").trim();
  const query = String(formData.get("query") ?? "");
  if (!name) return { error: "Give the screen a name." };
  try {
    // A2.3: re-saving a screen with the same rule keeps its setup version (and
    // so its change notifications); a different rule drops them.
    const existing = (await listSavedScreens().catch(() => [] as SavedScreen[])).find(
      (s) => s.name === name.slice(0, 80),
    );
    const keep = existing?.setup_version_id && ruleOf(existing.query) === ruleOf(query);
    await saveScreen(name.slice(0, 80), query, {
      setupVersionId: keep ? existing?.setup_version_id : null,
      notifyOnChange: keep ? Boolean(existing?.notify_on_change) : false,
    });
    revalidatePath("/screener");
    return { saved: name };
  } catch (err) {
    if (err instanceof UnauthenticatedError) return { error: "Sign in to save screens." };
    if (err instanceof AuthedApiError && err.status === 409) return { error: err.message };
    return { error: "The screen could not be saved." };
  }
}

export async function deleteScreenAction(formData: FormData): Promise<void> {
  const id = Number(formData.get("id"));
  if (!Number.isInteger(id) || id <= 0) return;
  try {
    await deleteScreen(id);
  } catch (err) {
    if (!(err instanceof UnauthenticatedError)) throw err;
  }
  revalidatePath("/screener");
}

export type SetupActionState = {
  saved?: { id: number; name: string; version: number };
  error?: string;
};

/** A2.2: save the rule in the editor as a new setup (version 1). */
export async function saveSetupAction(
  _prev: SetupActionState,
  formData: FormData,
): Promise<SetupActionState> {
  const name = String(formData.get("name") ?? "").trim();
  const rule = String(formData.get("rule") ?? "").trim();
  if (!name) return { error: "Give the setup a name." };
  if (!rule) return { error: "Write a rule first." };
  try {
    const setup = await createSetup({ name: name.slice(0, 120), rule, kind: "screen" });
    revalidatePath("/setups");
    return { saved: { id: setup.id, name: setup.name, version: setup.latest_version.version } };
  } catch (err) {
    if (err instanceof UnauthenticatedError) return { error: "Sign in to save setups." };
    if (err instanceof AuthedApiError && err.status === 422) {
      return { error: "The rule does not compile. Fix it before saving." };
    }
    if (err instanceof AuthedApiError && err.status === 409) return { error: err.message };
    return { error: "The setup could not be saved." };
  }
}

/** A2.2: fork a preset into a setup of your own. */
export async function forkPresetAction(
  _prev: SetupActionState,
  formData: FormData,
): Promise<SetupActionState> {
  const id = Number(formData.get("id"));
  if (!Number.isInteger(id) || id <= 0) return { error: "Choose a preset." };
  try {
    const setup = await forkSetup(id);
    revalidatePath("/setups");
    return { saved: { id: setup.id, name: setup.name, version: setup.latest_version.version } };
  } catch (err) {
    if (err instanceof UnauthenticatedError) return { error: "Sign in to fork presets." };
    if (err instanceof AuthedApiError && err.status === 409) return { error: err.message };
    return { error: "The preset could not be forked." };
  }
}

export type NotifyActionState = { error?: string; on?: boolean };

/**
 * A2.3: "Notify me when members change" on a saved screen. The nightly
 * `screen-runs` job judges a setup version, so a screen whose rule is only
 * text in its URL gets one first: the user's own setup with that exact rule
 * (same canonical hash) if there is one, else a new setup named after the
 * screen.
 */
export async function toggleScreenNotifyAction(
  _prev: NotifyActionState,
  formData: FormData,
): Promise<NotifyActionState> {
  const id = Number(formData.get("id"));
  const on = formData.get("notify") === "on";
  if (!Number.isInteger(id) || id <= 0) return { error: "Choose a screen." };
  try {
    const screen = (await listSavedScreens()).find((s) => s.id === id);
    if (!screen) return { error: "That screen is gone." };
    if (!on || screen.setup_version_id) {
      const saved = await setScreenNotify(id, on);
      revalidatePath("/screener");
      return { on: Boolean(saved.notify_on_change) };
    }
    const rule = ruleOf(screen.query);
    if (!rule) return { error: "Add a rule to this screen first." };
    const check = await checkRule(rule);
    if (!check.valid || !check.hash) return { error: "The screen's rule does not compile." };
    const mine = (await listSetups()).find(
      (s) => s.owned && !s.archived_at && s.latest_version.rule_hash === check.hash,
    );
    const versionId =
      mine?.latest_version.id ??
      (await createSetup({ name: screen.name.slice(0, 120), rule, kind: "screen" })).latest_version
        .id;
    const saved = await saveScreen(screen.name, screen.query, {
      setupVersionId: versionId,
      notifyOnChange: true,
    });
    revalidatePath("/screener");
    revalidatePath("/setups");
    return { on: Boolean(saved.notify_on_change) };
  } catch (err) {
    if (err instanceof UnauthenticatedError) return { error: "Sign in first." };
    if (err instanceof AuthedApiError && (err.status === 400 || err.status === 409)) {
      return { error: apiDetail(err.detail, "The setting could not be saved.") };
    }
    return { error: "The setting could not be saved." };
  }
}

export type RuleDraftState = {
  rule?: string;
  valid?: boolean;
  error?: string;
  note?: string;
  model?: string;
};

/** A8.2: the server's model drafts a rule from words; the rule checker judges it. */
export async function draftRuleAction(text: string): Promise<RuleDraftState> {
  const words = text.trim();
  if (words.length < 3) return { error: "Describe the screen in a few words." };
  try {
    const out = await draftRule(words.slice(0, 500));
    return {
      rule: out.rule,
      valid: out.check.valid,
      error: out.check.valid ? undefined : (out.check.error?.message ?? "Not a valid rule."),
      note: out.note,
      model: `${out.provider} ${out.model}`,
    };
  } catch (err) {
    if (err instanceof UnauthenticatedError) return { error: "Sign in to draft rules." };
    if (err instanceof AuthedApiError) {
      return { error: apiDetail(err.detail, "The draft could not be made just now.") };
    }
    return { error: "The draft could not be made just now." };
  }
}
