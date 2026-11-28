/** Invite requests while sign-up is closed: the server action. */
import { beforeEach, describe, expect, it, vi } from "vitest";

const hit = vi.fn();
const send = vi.fn();
let mode = "closed";

vi.mock("@/lib/rate-limit", () => ({ hit: (...args: unknown[]) => hit(...args) }));
vi.mock("@/lib/signup-gate", () => ({ signupMode: () => mode }));
vi.mock("next/headers", () => ({
  headers: async () => new Headers({ "x-forwarded-for": "203.0.113.9" }),
}));

vi.mock("@/lib/invite-mail", async (original) => ({
  ...(await original<typeof import("@/lib/invite-mail")>()),
  sendInviteRequest: (...args: unknown[]) => send(...args),
}));

describe("requestInviteAction", () => {
  function form(fields: Record<string, string>): FormData {
    const data = new FormData();
    for (const [k, v] of Object.entries(fields)) data.set(k, v);
    return data;
  }
  const valid = { name: " Ada ", email: "ada@example.com ", note: "Replay 2020" };

  beforeEach(() => {
    mode = "closed";
    hit.mockReset().mockResolvedValue({ allowed: true, retryAfterSeconds: 0 });
    send.mockReset().mockResolvedValue({ ok: true });
  });

  it("sends a valid request, trimmed, keyed on the client address", async () => {
    const { requestInviteAction } = await import("@/app/(public)/(auth)/signup/invite-actions");
    await expect(requestInviteAction({ status: "idle" }, form(valid))).resolves.toEqual({
      status: "sent",
    });
    expect(send).toHaveBeenCalledWith({
      name: "Ada",
      email: "ada@example.com",
      note: "Replay 2020",
    });
    expect(hit.mock.calls[0][0]).toBe("invite:ip:203.0.113.9");
  });

  it("drops honeypot submissions without sending", async () => {
    const { requestInviteAction } = await import("@/app/(public)/(auth)/signup/invite-actions");
    const result = await requestInviteAction(
      { status: "idle" },
      form({ ...valid, company: "Spam Inc" }),
    );
    expect(result).toEqual({ status: "sent" });
    expect(send).not.toHaveBeenCalled();
  });

  it("rejects a bad email, a rate-limited address, and an open sign-up", async () => {
    const { requestInviteAction } = await import("@/app/(public)/(auth)/signup/invite-actions");
    expect(
      await requestInviteAction({ status: "idle" }, form({ ...valid, email: "nope" })),
    ).toMatchObject({
      status: "error",
      error: "Add a valid email",
    });
    hit.mockResolvedValueOnce({ allowed: false, retryAfterSeconds: 60 });
    expect((await requestInviteAction({ status: "idle" }, form(valid))).status).toBe("error");
    mode = "open";
    expect((await requestInviteAction({ status: "idle" }, form(valid))).status).toBe("error");
    expect(send).not.toHaveBeenCalled();
  });

  it("explains when mail is not set up", async () => {
    send.mockResolvedValue({ ok: false, reason: "not_configured" });
    const { requestInviteAction } = await import("@/app/(public)/(auth)/signup/invite-actions");
    expect((await requestInviteAction({ status: "idle" }, form(valid))).error).toMatch(
      /not switched on/,
    );
  });
});
