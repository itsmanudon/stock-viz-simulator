/**
 * Who may open a new account (owner, 27 Nov 2026: a switch, not removed code).
 *
 * `SIGNUP_MODE` (web, read at request time):
 * - `closed` (the default): no new accounts, except the very first one on an
 *   empty database, so a fresh self-hosted install can still be set up;
 * - `allowlist`: only the addresses in `SIGNUP_ALLOWLIST` (comma-separated,
 *   case ignored);
 * - `open`: anyone (the old behaviour; e2e and CI set it).
 * Existing accounts always sign in. Pure; `lib/signup-gate.ts` reads the env
 * and the user count.
 */

export type SignupMode = "open" | "allowlist" | "closed";

export function parseSignupMode(raw: string | undefined): SignupMode {
  const v = (raw ?? "").trim().toLowerCase();
  return v === "open" || v === "allowlist" ? v : "closed";
}

export function parseAllowlist(raw: string | undefined): Set<string> {
  return new Set(
    (raw ?? "")
      .split(",")
      .map((e) => e.trim().toLowerCase())
      .filter(Boolean),
  );
}

/** True when a new account may be created for `email`. */
export function signupAllowed(args: {
  mode: SignupMode;
  allowlist: Set<string>;
  email: string;
  userCount: number;
}): boolean {
  if (args.mode === "open") return true;
  if (args.userCount === 0) return true; // the first account on an empty install
  if (args.mode === "allowlist") return args.allowlist.has(args.email.trim().toLowerCase());
  return false;
}

export const SIGNUP_CLOSED_MESSAGE =
  "StockViz is invite only for now, so new accounts cannot be created. Existing accounts can still sign in.";

/**
 * Marketing buttons while new accounts are not open to everyone (owner, 28 Nov
 * 2026, before sharing the site for review): a link to `/signup` would land a
 * visitor on the "invite only" message, so it becomes a public page instead.
 * When both buttons of a pair would then point to the same page, the second
 * goes to the docs.
 */
export type CtaLink = { href: string; label: string };

export const CLOSED_CTA: CtaLink = { href: "/markets", label: "Explore markets" };
export const CLOSED_CTA_ALT: CtaLink = { href: "/docs", label: "Read the docs" };

function isSignupLink(link: CtaLink): boolean {
  return link.href.split("?")[0] === "/signup";
}

export function ctaPair(
  mode: SignupMode,
  primary: CtaLink,
  secondary: CtaLink,
): [CtaLink, CtaLink] {
  if (mode === "open") return [primary, secondary];
  const first = isSignupLink(primary) ? CLOSED_CTA : primary;
  let second = isSignupLink(secondary) ? CLOSED_CTA : secondary;
  if (second.href === first.href) {
    second = first.href === CLOSED_CTA_ALT.href ? CLOSED_CTA : CLOSED_CTA_ALT;
  }
  return [first, second];
}
