"use server";

import bcrypt from "bcryptjs";
import { AuthError } from "next-auth";
import { headers } from "next/headers";
import { redirect } from "next/navigation";
import { z } from "zod";

import { signIn } from "@/auth";
import { hit, reset } from "@/lib/rate-limit";
import { safeRedirect } from "@/lib/redirect";
import { createUser, findUserByEmail } from "@/lib/users";

const SignupSchema = z.object({
  name: z.string().min(1).max(120),
  email: z.email().max(320),
  password: z.string().min(8, "Password must be at least 8 characters").max(128),
});

export type AuthFormState = {
  error?: string;
};

// Credential auth is the one place an attacker can grind: bcrypt.compare with
// no counter answers as fast as the server can hash. Windows are keyed on the
// email so one account under attack doesn't lock out everyone else, and on the
// client IP so a spray across many emails is also bounded.
const LOGIN_LIMIT = 8;
const LOGIN_WINDOW_MS = 15 * 60 * 1000;
const SIGNUP_LIMIT = 5;
const SIGNUP_WINDOW_MS = 60 * 60 * 1000;

async function clientIp(): Promise<string> {
  const h = await headers();
  // Vercel and most proxies set x-forwarded-for; left-most hop is the client.
  const forwarded = h.get("x-forwarded-for");
  if (forwarded) return forwarded.split(",")[0]?.trim() || "unknown";
  return h.get("x-real-ip") ?? "unknown";
}

function throttled(retryAfterSeconds: number): AuthFormState {
  const minutes = Math.ceil(retryAfterSeconds / 60);
  return {
    error: `Too many attempts. Try again in ${minutes} minute${minutes === 1 ? "" : "s"}.`,
  };
}

export async function signupAction(
  _prev: AuthFormState,
  formData: FormData,
): Promise<AuthFormState> {
  const parsed = SignupSchema.safeParse({
    name: formData.get("name"),
    email: formData.get("email"),
    password: formData.get("password"),
  });
  if (!parsed.success) {
    return { error: parsed.error.issues[0]?.message ?? "Invalid input" };
  }

  const ip = await clientIp();
  const gate = hit(`signup:${ip}`, SIGNUP_LIMIT, SIGNUP_WINDOW_MS);
  if (!gate.allowed) return throttled(gate.retryAfterSeconds);

  const existing = await findUserByEmail(parsed.data.email);
  if (existing) {
    return { error: "An account with that email already exists" };
  }

  const passwordHash = await bcrypt.hash(parsed.data.password, 12);
  try {
    await createUser({
      email: parsed.data.email,
      name: parsed.data.name,
      passwordHash,
    });
  } catch (err) {
    // The check above is not atomic: two concurrent signups for the same
    // address both pass it and the second hits the unique index. Turn that
    // into the same friendly message instead of an unhandled 500.
    if (isUniqueViolation(err)) {
      return { error: "An account with that email already exists" };
    }
    throw err;
  }

  // Roll straight into a signed-in session so the user lands on the page they
  // were originally trying to reach. ``redirect`` here would clash with
  // NextAuth's own redirect so we let signIn handle it.
  await signIn("credentials", {
    email: parsed.data.email,
    password: parsed.data.password,
    redirectTo: safeRedirect(formData.get("callbackUrl")),
  });

  // signIn redirects; this is unreachable but keeps the return type honest.
  return {};
}

const LoginSchema = z.object({
  email: z.email().max(320),
  password: z.string().min(1).max(128),
});

export async function loginAction(
  _prev: AuthFormState,
  formData: FormData,
): Promise<AuthFormState> {
  const parsed = LoginSchema.safeParse({
    email: formData.get("email"),
    password: formData.get("password"),
  });
  if (!parsed.success) {
    return { error: "Enter a valid email and password" };
  }

  const ip = await clientIp();
  const emailKey = `login:email:${parsed.data.email}`;
  const ipKey = `login:ip:${ip}`;
  for (const [key, limit] of [
    [emailKey, LOGIN_LIMIT],
    [ipKey, LOGIN_LIMIT * 3],
  ] as const) {
    const gate = hit(key, limit, LOGIN_WINDOW_MS);
    if (!gate.allowed) return throttled(gate.retryAfterSeconds);
  }

  try {
    await signIn("credentials", {
      email: parsed.data.email,
      password: parsed.data.password,
      redirectTo: safeRedirect(formData.get("callbackUrl")),
    });
  } catch (err) {
    if (err instanceof AuthError) {
      return { error: "Invalid email or password" };
    }
    // signIn throws a redirect sentinel on success — clear the counters so a
    // couple of typos before a correct password don't leave the user throttled.
    reset(emailKey);
    reset(ipKey);
    // ``redirect`` throws a sentinel error inside server actions; let it bubble.
    throw err;
  }

  return {};
}

export async function signOutAction(): Promise<never> {
  const { signOut } = await import("@/auth");
  await signOut({ redirectTo: "/" });
  redirect("/");
}

export async function signInWithGoogleAction(formData?: FormData): Promise<never> {
  // Forwarded from the same login/signup form as the credentials button via
  // ``<button formAction={...}>``, so the hidden ``callbackUrl`` input is in
  // ``formData`` when present.
  const callback = safeRedirect(formData?.get("callbackUrl") ?? null);
  await signIn("google", { redirectTo: callback });
  redirect(callback);
}

/** Postgres unique-violation (23505), as surfaced by node-postgres. */
function isUniqueViolation(err: unknown): boolean {
  return typeof err === "object" && err !== null && "code" in err && err.code === "23505";
}
