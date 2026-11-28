/** The signup switch (27 Nov 2026): who may open a new account. */
import { describe, expect, it } from "vitest";

import { SIGN_IN_ERRORS, googleSignInRefusal } from "@/lib/oauth-linking";
import {
  INVITE_EMAIL,
  ctaPair,
  inviteMailto,
  parseAllowlist,
  parseSignupMode,
  signupAllowed,
} from "@/lib/signup-policy";

const allow = parseAllowlist(" Me@Example.com, friend@example.com ,, ");

describe("signup policy", () => {
  it("defaults to closed for anything but open or allowlist", () => {
    expect(parseSignupMode(undefined)).toBe("closed");
    expect(parseSignupMode("")).toBe("closed");
    expect(parseSignupMode("yes")).toBe("closed");
    expect(parseSignupMode(" OPEN ")).toBe("open");
    expect(parseSignupMode("Allowlist")).toBe("allowlist");
    expect([...allow]).toEqual(["me@example.com", "friend@example.com"]);
  });

  it("closed lets only the first account on an empty install through", () => {
    expect(signupAllowed({ mode: "closed", allowlist: allow, email: "a@b.c", userCount: 3 })).toBe(
      false,
    );
    expect(signupAllowed({ mode: "closed", allowlist: allow, email: "a@b.c", userCount: 0 })).toBe(
      true,
    );
  });

  it("allowlist matches addresses ignoring case and spaces", () => {
    expect(
      signupAllowed({
        mode: "allowlist",
        allowlist: allow,
        email: " ME@example.com",
        userCount: 9,
      }),
    ).toBe(true);
    expect(
      signupAllowed({
        mode: "allowlist",
        allowlist: allow,
        email: "other@example.com",
        userCount: 9,
      }),
    ).toBe(false);
  });

  it("open lets anyone in", () => {
    expect(
      signupAllowed({ mode: "open", allowlist: new Set(), email: "x@y.z", userCount: 50 }),
    ).toBe(true);
  });

  it("the login page has words for a closed Google sign-up", () => {
    expect(SIGN_IN_ERRORS.SignupClosed).toMatch(/invite only/);
    expect(googleSignInRefusal({ emailVerified: true, existing: null })).toBeNull();
  });
});

describe("marketing buttons while signup is not open (28 Nov 2026)", () => {
  const signup = { href: "/signup", label: "Create free account" };
  const markets = { href: "/markets", label: "Explore markets" };
  const replay = { href: "/replay", label: "Start a replay" };

  it("keeps the buttons when signup is open", () => {
    expect(ctaPair("open", signup, markets)).toEqual([signup, markets]);
  });

  it("swaps a /signup button for a public page, never two of the same", () => {
    expect(ctaPair("closed", signup, markets)).toEqual([
      markets,
      { href: "/docs", label: "Read the docs" },
    ]);
    expect(ctaPair("allowlist", replay, { href: "/signup?x=1", label: "Join" })).toEqual([
      replay,
      markets,
    ]);
    expect(ctaPair("closed", replay, markets)).toEqual([replay, markets]);
  });
});

describe("inviteMailto", () => {
  it("addresses the owner with the visitor's details", () => {
    const url = inviteMailto({
      name: " Ada ",
      email: "ada@example.com",
      note: "Replay 2020 & trade it",
    });
    expect(url.startsWith(`mailto:${INVITE_EMAIL}?subject=`)).toBe(true);
    const params = new URLSearchParams(url.split("?")[1]);
    expect(params.get("subject")).toBe("StockViz invite request from Ada");
    const body = params.get("body") ?? "";
    expect(body).toContain("Name: Ada\nEmail: ada@example.com");
    expect(body).toContain("What I would try first:\nReplay 2020 & trade it");
  });

  it("leaves out an empty note and caps a long one", () => {
    const bare = new URLSearchParams(
      inviteMailto({ name: "", email: "", note: "  " }).split("?")[1],
    );
    expect(bare.get("subject")).toBe("StockViz invite request");
    expect(bare.get("body")).not.toContain("try first");
    const long = new URLSearchParams(
      inviteMailto({ name: "x", email: "y", note: "z".repeat(5000) }).split("?")[1],
    );
    expect((long.get("body") ?? "").match(/z+$/)?.[0]).toHaveLength(1000);
  });
});
