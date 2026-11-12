"use server";

import { revalidatePath } from "next/cache";

import { markAllNotificationsRead, markNotificationRead } from "@/lib/api/notifications";
import { AuthedApiError, UnauthenticatedError } from "@/lib/api/server";

async function quietly(run: () => Promise<unknown>): Promise<void> {
  try {
    await run();
  } catch (err) {
    if (err instanceof UnauthenticatedError) return;
    if (err instanceof AuthedApiError && err.status === 404) return;
    throw err;
  }
}

export async function markNotificationReadAction(formData: FormData): Promise<void> {
  const id = Number(formData.get("id"));
  if (!Number.isFinite(id)) return;
  await quietly(() => markNotificationRead(id));
  revalidatePath("/notifications");
}

export async function markAllNotificationsReadAction(): Promise<void> {
  await quietly(() => markAllNotificationsRead());
  revalidatePath("/notifications");
}
