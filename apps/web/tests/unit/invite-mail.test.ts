/** Invite requests while sign-up is closed: the Brevo mail helper. */
import { describe, expect, it, vi } from "vitest";

const mail = await import("@/lib/invite-mail");

describe("sendInviteRequest", () => {
  const request = { name: "Ada", email: "ada@example.com", note: "Replay 2020" };
  const env = {
    BREVO_API_KEY: "test-key",
    INVITE_FROM_EMAIL: "invites@example.com",
  } as unknown as NodeJS.ProcessEnv;

  it("posts to Brevo with the owner as recipient and the visitor as reply-to", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(new Response("{}", { status: 201 }));
    await expect(mail.sendInviteRequest(request, { env, fetchImpl })).resolves.toEqual({
      ok: true,
    });
    const [url, init] = fetchImpl.mock.calls[0];
    expect(url).toBe("https://api.brevo.com/v3/smtp/email");
    expect(init.headers["api-key"]).toBe("test-key");
    const body = JSON.parse(init.body);
    expect(body.sender.email).toBe("invites@example.com");
    expect(body.to).toEqual([{ email: "mananjariwala01@outlook.com" }]);
    expect(body.replyTo).toEqual({ email: "ada@example.com", name: "Ada" });
    expect(body.subject).toBe("StockViz invite request from Ada");
    expect(body.textContent).toContain("What they would try first:\nReplay 2020");
  });

  it("uses INVITE_TO_EMAIL when set", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(new Response("{}", { status: 201 }));
    await mail.sendInviteRequest(request, {
      env: { ...env, INVITE_TO_EMAIL: "inbox@example.com" },
      fetchImpl,
    });
    expect(JSON.parse(fetchImpl.mock.calls[0][1].body).to).toEqual([
      { email: "inbox@example.com" },
    ]);
  });

  it("refuses without a key or sender and reports Brevo failures", async () => {
    const fetchImpl = vi.fn();
    await expect(
      mail.sendInviteRequest(request, { env: {} as unknown as NodeJS.ProcessEnv, fetchImpl }),
    ).resolves.toEqual({
      ok: false,
      reason: "not_configured",
    });
    expect(fetchImpl).not.toHaveBeenCalled();
    const quiet = vi.spyOn(console, "error").mockImplementation(() => {});
    fetchImpl.mockResolvedValueOnce(new Response("{}", { status: 401 }));
    await expect(mail.sendInviteRequest(request, { env, fetchImpl })).resolves.toEqual({
      ok: false,
      reason: "failed",
    });
    fetchImpl.mockRejectedValueOnce(new TypeError("fetch failed"));
    await expect(mail.sendInviteRequest(request, { env, fetchImpl })).resolves.toEqual({
      ok: false,
      reason: "failed",
    });
    quiet.mockRestore();
  });
});
