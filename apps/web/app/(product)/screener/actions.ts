"use server";

import { revalidatePath } from "next/cache";

import { deleteScreen, saveScreen } from "@/lib/api/screens";
import { AuthedApiError, UnauthenticatedError } from "@/lib/api/server";
import { createSetup, forkSetup } from "@/lib/api/setups-server";

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
    await saveScreen(name.slice(0, 80), query);
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
