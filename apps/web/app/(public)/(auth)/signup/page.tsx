import type { Metadata } from "next";
import { Suspense } from "react";

import { signupMode } from "@/lib/signup-gate";

import { InviteRequest } from "./invite-request";
import { SignupForm } from "./signup-form";

export function generateMetadata(): Metadata {
  return { title: signupMode() === "closed" ? "Request an invite" : "Create your account" };
}
// The signup switch is read per request, never baked in at build time.
export const dynamic = "force-dynamic";

export default function SignupPage() {
  const mode = signupMode();
  if (mode === "closed") return <InviteRequest />;
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
