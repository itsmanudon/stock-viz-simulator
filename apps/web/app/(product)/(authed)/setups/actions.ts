"use server";

import { revalidatePath } from "next/cache";

import { UnauthenticatedError } from "@/lib/api/server";
import { archiveSetup, forkSetup } from "@/lib/api/setups-server";

function setupId(formData: FormData): number | null {
  const id = Number(formData.get("id"));
  return Number.isInteger(id) && id > 0 ? id : null;
}

/** A2.2: copy a preset (or one of your setups) into a new setup you own. */
export async function forkSetupAction(formData: FormData): Promise<void> {
  const id = setupId(formData);
  if (id === null) return;
  try {
    await forkSetup(id);
  } catch (err) {
    if (!(err instanceof UnauthenticatedError)) throw err;
  }
  revalidatePath("/setups");
}

/** A2.2: hide a setup of yours; its versions stay readable. */
export async function archiveSetupAction(formData: FormData): Promise<void> {
  const id = setupId(formData);
  if (id === null) return;
  try {
    await archiveSetup(id);
  } catch (err) {
    if (!(err instanceof UnauthenticatedError)) throw err;
  }
  revalidatePath("/setups");
}
