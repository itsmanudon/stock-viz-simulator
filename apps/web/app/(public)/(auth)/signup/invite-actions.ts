"use server";

import { headers } from "next/headers";
import { z } from "zod";

import { clientAddress } from "@/lib/client-address";
import { sendInviteRequest } from "@/lib/invite-mail";
import { hit } from "@/lib/rate-limit";
import { signupMode } from "@/lib/signup-gate";

export type InviteFormState = { status: "idle" | "sent" | "error"; error?: string };

const InviteSchema = z.object({
  name: z.string().trim().min(1, "Add your name").max(120),
  email: z.email("Add a valid email").max(320),
  note: z.string().trim().max(1000).default(""),
});

// A few per address per hour: enough for a typo and a retry, not for a flood.
const INVITE_LIMIT = 3;
const INVITE_WINDOW_MS = 60 * 60 * 1000;

export async function requestInviteAction(
  _prev: InviteFormState,
  formData: FormData,
): Promise<InviteFormState> {
  if (signupMode() !== "closed") {
    return { status: "error", error: "Sign-up is open: create an account instead." };
  }
  // Honeypot: a field people never see. Bots that fill it get a quiet "sent".
  if (String(formData.get("company") ?? "").trim()) return { status: "sent" };

  const parsed = InviteSchema.safeParse({
    name: String(formData.get("name") ?? ""),
    email: String(formData.get("email") ?? "").trim(),
    note: String(formData.get("note") ?? ""),
  });
  if (!parsed.success) {
    return { status: "error", error: parsed.error.issues[0]?.message ?? "Check the form" };
  }

  const ip = clientAddress(await headers());
  const limit = await hit(`invite:ip:${ip}`, INVITE_LIMIT, INVITE_WINDOW_MS);
  if (!limit.allowed) {
    return { status: "error", error: "Too many requests from here. Try again in an hour." };
  }

  const result = await sendInviteRequest(parsed.data);
  if (result.ok) return { status: "sent" };
  return {
    status: "error",
    error:
      result.reason === "not_configured"
        ? "Invite requests are not switched on yet. Please try again later."
        : "Your request could not be sent. Please try again in a minute.",
  };
}
