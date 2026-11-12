import { beforeEach, describe, expect, it, vi } from "vitest";

const hit = vi.fn();
const reset = vi.fn();
const signIn = vi.fn();

vi.mock("@/lib/rate-limit", () => ({
  hit: (...args: unknown[]) => hit(...args),
  reset: (...args: unknown[]) => reset(...args),
}));
vi.mock("next-auth", () => ({ AuthError: class AuthError extends Error {} }));
vi.mock("@/auth", () => ({ signIn: (...args: unknown[]) => signIn(...args) }));
vi.mock("next/headers", () => ({
  headers: async () => new Headers({ "x-forwarded-for": "203.0.113.9" }),
}));
vi.mock("@/lib/users", () => ({ createUser: vi.fn(), findUserByEmail: vi.fn() }));

const { loginAction } = await import("@/app/(public)/(auth)/actions");

function form(): FormData {
  const data = new FormData();
  data.set("email", "me@example.com");
  data.set("password", "right-password");
  return data;
}

describe("loginAction counters (audit OP-8)", () => {
  beforeEach(() => {
    hit.mockReset().mockResolvedValue({ allowed: true, retryAfterSeconds: 0 });
    reset.mockReset().mockResolvedValue(undefined);
    signIn.mockReset();
  });

  it("clears the email counter after a success, never the address counter", async () => {
    // NextAuth signals success by throwing its redirect sentinel.
    signIn.mockRejectedValue(new Error("NEXT_REDIRECT"));

    await expect(loginAction({}, form())).rejects.toThrow("NEXT_REDIRECT");

    expect(reset).toHaveBeenCalledTimes(1);
    expect(reset).toHaveBeenCalledWith("login:email:me@example.com");
  });

  it("counts both the email and the address before checking the password", async () => {
    signIn.mockRejectedValue(new Error("NEXT_REDIRECT"));
    await expect(loginAction({}, form())).rejects.toThrow();

    expect(hit.mock.calls.map((call) => call[0])).toEqual([
      "login:email:me@example.com",
      "login:ip:203.0.113.9",
    ]);
  });
});
