import type { Metadata } from "next";
import { Suspense } from "react";

import { signupMode } from "@/lib/signup-gate";

import { LoginForm } from "./login-form";

export const metadata: Metadata = { title: "Sign in" };

export default function LoginPage() {
  return (
    <Suspense>
      {/* The signup switch: no "Sign up" link while new accounts are closed. */}
      <LoginForm signupOpen={signupMode() !== "closed"} />
    </Suspense>
  );
}
