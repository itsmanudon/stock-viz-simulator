import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";

import { signupMode } from "@/lib/signup-gate";
import { SIGNUP_CLOSED_MESSAGE } from "@/lib/signup-policy";

import { SignupForm } from "./signup-form";

export const metadata: Metadata = { title: "Create your account" };
// The signup switch is read per request, never baked in at build time.
export const dynamic = "force-dynamic";

export default function SignupPage() {
  const mode = signupMode();
  if (mode === "closed") {
    return (
      <div className="mx-auto max-w-md space-y-4 py-16 text-center" data-testid="signup-closed">
        <h1 className="text-2xl font-semibold tracking-[-0.025em]">Invite Only</h1>
        <p className="text-sm text-text-secondary">{SIGNUP_CLOSED_MESSAGE}</p>
        <p className="text-sm">
          <Link href="/login" className="font-medium underline">
            Sign in
          </Link>
        </p>
      </div>
    );
  }
  return (
    <div className="space-y-2">
      {mode === "allowlist" ? (
        <p className="text-center text-xs text-text-secondary" data-testid="signup-invite-note">
          Invite only: sign up with the address you were invited with.
        </p>
      ) : null}
      <Suspense>
        <SignupForm />
      </Suspense>
    </div>
  );
}
