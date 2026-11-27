import "server-only";

/** Reads `SIGNUP_MODE` / `SIGNUP_ALLOWLIST` at request time (see lib/signup-policy.ts). */

import {
  type SignupMode,
  parseAllowlist,
  parseSignupMode,
  signupAllowed,
} from "@/lib/signup-policy";
import { countUsers } from "@/lib/users";

export function signupMode(): SignupMode {
  return parseSignupMode(process.env.SIGNUP_MODE);
}

export async function canCreateAccount(email: string): Promise<boolean> {
  const mode = signupMode();
  if (mode === "open") return true;
  return signupAllowed({
    mode,
    allowlist: parseAllowlist(process.env.SIGNUP_ALLOWLIST),
    email,
    userCount: await countUsers(),
  });
}
