/**
 * Whether a Google sign-in may use the account its email names (audit OP-4).
 *
 * Sign-up does not verify email addresses, so an account with a password
 * proves nothing about who owns its address. Letting Google attach to it
 * would let whoever registered a victim's address first keep password access
 * to the account the victim then uses through Google. So Google signs in to an
 * account only when Google itself created it (no password), and only for an
 * address Google says it verified. Holders of a password account keep using
 * the password.
 */

export type GoogleSignInRefusal = "OAuthAccountNotLinked" | "GoogleEmailUnverified";

export function googleSignInRefusal(args: {
  emailVerified: boolean;
  existing: { password_hash: string | null } | null;
}): GoogleSignInRefusal | null {
  if (!args.emailVerified) return "GoogleEmailUnverified";
  if (args.existing?.password_hash) return "OAuthAccountNotLinked";
  return null;
}

/** What the login page says for each refusal; NextAuth passes it as ?error=. */
export const SIGN_IN_ERRORS: Record<string, string> = {
  OAuthAccountNotLinked:
    "This email already has a StockViz password. Sign in with your password instead of Google.",
  GoogleEmailUnverified: "Google has not verified this email address, so it cannot sign you in.",
};
