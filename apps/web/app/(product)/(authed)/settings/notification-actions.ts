"use server";

import { revalidatePath } from "next/cache";

import { apiDetail } from "@/lib/api-error-detail";
import {
  type NotificationChannel,
  type NotificationChannelInput,
  putNotificationChannel,
  testNotificationChannel,
} from "@/lib/api/notifications";
import { AuthedApiError, UnauthenticatedError } from "@/lib/api/server";

export type ChannelActionState = { ok?: string; error?: string };

const CHANNELS = ["webhook", "email", "telegram"] as const;

function text(formData: FormData, name: string): string | undefined {
  const value = formData.get(name);
  return typeof value === "string" ? value.trim() : undefined;
}

/** The change a channel's form asks for (pure, exported for tests). */
export async function channelChange(formData: FormData): Promise<NotificationChannelInput | null> {
  const channel = text(formData, "channel") as NotificationChannel["channel"] | undefined;
  if (!channel || !CHANNELS.includes(channel)) return null;
  const categories = (text(formData, "categories") ?? "").split(",").filter(Boolean);
  const change: NotificationChannelInput = {
    channel,
    enabled: formData.get("enabled") === "on",
    muted_categories: categories.filter((c) => formData.get(`send:${c}`) !== "on"),
  };
  if (channel === "webhook") {
    change.url = text(formData, "url") ?? "";
    // Write-only: an empty field leaves the stored secret as it is.
    const secret = text(formData, "secret");
    if (secret) change.secret = secret;
  } else if (channel === "email") {
    change.address = text(formData, "address") ?? "";
  } else {
    change.chat_id = text(formData, "chat_id") ?? "";
  }
  return change;
}

export async function saveChannelAction(
  _prev: ChannelActionState,
  formData: FormData,
): Promise<ChannelActionState> {
  const change = await channelChange(formData);
  if (!change) return { error: "Unknown channel." };
  try {
    await putNotificationChannel(change);
    revalidatePath("/settings");
    return { ok: "Saved." };
  } catch (err) {
    if (err instanceof UnauthenticatedError) return { error: "Sign in first." };
    if (err instanceof AuthedApiError && [400, 409, 422].includes(err.status)) {
      return { error: apiDetail(err.detail, "Not saved: check the fields.") };
    }
    return { error: "The channel could not be saved." };
  }
}

export async function testChannelAction(
  _prev: ChannelActionState,
  formData: FormData,
): Promise<ChannelActionState> {
  const channel = text(formData, "channel") as NotificationChannel["channel"] | undefined;
  if (!channel || !CHANNELS.includes(channel)) return { error: "Unknown channel." };
  try {
    const result = await testNotificationChannel(channel);
    return result.ok ? { ok: "Test sent." } : { error: `Test failed: ${result.detail}` };
  } catch (err) {
    if (err instanceof UnauthenticatedError) return { error: "Sign in first." };
    if (err instanceof AuthedApiError && [409, 422, 429].includes(err.status)) {
      return { error: apiDetail(err.detail, "The test could not be sent.") };
    }
    return { error: "The test could not be sent." };
  }
}
