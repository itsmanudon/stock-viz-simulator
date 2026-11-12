import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { SIGN_IN_ERRORS, googleSignInRefusal } from "@/lib/oauth-linking";

let search = "";
vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(search),
}));
vi.mock("@/app/(public)/(auth)/actions", () => ({
  loginAction: vi.fn(),
  signInWithGoogleAction: vi.fn(),
}));

const { LoginForm } = await import("@/app/(public)/(auth)/login/login-form");

describe("Google sign-in linking (audit OP-4)", () => {
  it("opens a new account, or one Google created, for a verified address", () => {
    expect(googleSignInRefusal({ emailVerified: true, existing: null })).toBeNull();
    expect(
      googleSignInRefusal({ emailVerified: true, existing: { password_hash: null } }),
    ).toBeNull();
  });

  it("never attaches to an account that has a password", () => {
    expect(
      googleSignInRefusal({ emailVerified: true, existing: { password_hash: "$2b$hash" } }),
    ).toBe("OAuthAccountNotLinked");
  });

  it("refuses an address Google has not verified", () => {
    expect(googleSignInRefusal({ emailVerified: false, existing: null })).toBe(
      "GoogleEmailUnverified",
    );
  });

  it("explains a refusal on the login page", () => {
    search = "error=OAuthAccountNotLinked";
    render(<LoginForm />);

    expect(screen.getByRole("alert")).toHaveTextContent(SIGN_IN_ERRORS.OAuthAccountNotLinked);
  });
});
