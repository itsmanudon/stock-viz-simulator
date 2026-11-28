import "server-only";

/**
 * Invite requests by email through Brevo (owner, 28 Nov 2026): while sign-up
 * is closed, `/signup` posts a short request that the server sends to the
 * owner with Brevo's transactional API. The visitor never sees the owner's
 * address; replies go to the visitor (`replyTo`).
 *
 * Environment (server only):
 * - `BREVO_API_KEY`: required; without it requests are refused as "not set up".
 * - `INVITE_FROM_EMAIL`: a sender verified in that Brevo account.
 * - `INVITE_TO_EMAIL`: where requests go; defaults to the owner.
 */

const BREVO_URL = "https://api.brevo.com/v3/smtp/email";
const DEFAULT_TO = "mananjariwala01@outlook.com";

export type InviteRequest = { name: string; email: string; note: string };

export type InviteMailResult = { ok: true } | { ok: false; reason: "not_configured" | "failed" };

export function inviteMailConfigured(env: NodeJS.ProcessEnv = process.env): boolean {
  return Boolean(env.BREVO_API_KEY?.trim() && env.INVITE_FROM_EMAIL?.trim());
}

export function inviteMessage(request: InviteRequest): { subject: string; text: string } {
  const lines = [
    "New StockViz invite request.",
    "",
    `Name: ${request.name}`,
    `Email: ${request.email}`,
    "",
    "What they would try first:",
    request.note || "-",
    "",
    "Reply to this email to answer them directly.",
  ];
  return { subject: `StockViz invite request from ${request.name}`, text: lines.join("\n") };
}

export async function sendInviteRequest(
  request: InviteRequest,
  {
    env = process.env,
    fetchImpl = fetch,
  }: { env?: NodeJS.ProcessEnv; fetchImpl?: typeof fetch } = {},
): Promise<InviteMailResult> {
  const key = env.BREVO_API_KEY?.trim();
  const from = env.INVITE_FROM_EMAIL?.trim();
  if (!key || !from) return { ok: false, reason: "not_configured" };
  const to = env.INVITE_TO_EMAIL?.trim() || DEFAULT_TO;
  const { subject, text } = inviteMessage(request);
  try {
    const response = await fetchImpl(BREVO_URL, {
      method: "POST",
      headers: { "api-key": key, "content-type": "application/json", accept: "application/json" },
      body: JSON.stringify({
        sender: { name: "StockViz invites", email: from },
        to: [{ email: to }],
        replyTo: { email: request.email, name: request.name },
        subject,
        textContent: text,
      }),
      signal: AbortSignal.timeout(10_000),
    });
    if (response.ok) return { ok: true };
    console.error(`invite request: Brevo answered ${response.status}`);
    return { ok: false, reason: "failed" };
  } catch (error) {
    console.error("invite request: Brevo unreachable", error instanceof Error ? error.name : error);
    return { ok: false, reason: "failed" };
  }
}
