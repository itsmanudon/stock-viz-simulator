/**
 * Redirect-target validation for auth flows.
 *
 * The login and signup forms carry a `callbackUrl` so a user lands back where
 * they were. That value is attacker-controllable, so it must be confined to
 * same-app paths — otherwise the form is an open redirector, which phishing
 * campaigns use to borrow a trusted domain's credibility.
 *
 * Extracted from the server actions so it can be unit-tested: a `"use server"`
 * module may only export async functions.
 */

// Matches ASCII control characters, which can smuggle a newline into a
// Location header.
// biome-ignore lint/suspicious/noControlCharactersInRegex: detecting them is the point
const CONTROL_CHARS = /[\u0000-\u001f\u007f]/;

/**
 * Return `raw` if it is a safe in-app path, otherwise `"/"`.
 *
 * Rejects absolute URLs (`https://evil.com`), protocol-relative URLs
 * (`//evil.com`), backslash variants that some parsers normalise to slashes,
 * and anything that isn't a string.
 */
export function safeRedirect(raw: unknown): string {
  if (typeof raw !== "string") return "/";

  const value = raw.trim();
  if (!value.startsWith("/")) return "/";
  // `//host` and `/\host` are both protocol-relative in practice.
  if (value.startsWith("//") || value.startsWith("/\\")) return "/";
  if (CONTROL_CHARS.test(value)) return "/";
  return value;
}
