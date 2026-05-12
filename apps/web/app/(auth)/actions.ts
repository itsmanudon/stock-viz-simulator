"use server";

import bcrypt from "bcryptjs";
import { AuthError } from "next-auth";
import { redirect } from "next/navigation";
import { z } from "zod";

import { signIn } from "@/auth";
import { createUser, findUserByEmail } from "@/lib/users";

const SignupSchema = z.object({
  name: z.string().min(1).max(120),
  email: z.email().max(320),
  password: z.string().min(8, "Password must be at least 8 characters").max(128),
});

export type AuthFormState = {
  error?: string;
};

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

  const existing = await findUserByEmail(parsed.data.email);
  if (existing) {
    return { error: "An account with that email already exists" };
  }

  const passwordHash = await bcrypt.hash(parsed.data.password, 10);
  await createUser({
    email: parsed.data.email,
    name: parsed.data.name,
    passwordHash,
  });

  // Roll straight into a signed-in session so the user lands on the home page
  // ready to use. ``redirect`` here would clash with NextAuth's own redirect
  // so we let signIn handle it.
  await signIn("credentials", {
    email: parsed.data.email,
    password: parsed.data.password,
    redirectTo: "/",
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

  try {
    await signIn("credentials", {
      email: parsed.data.email,
      password: parsed.data.password,
      redirectTo: "/",
    });
  } catch (err) {
    if (err instanceof AuthError) {
      return { error: "Invalid email or password" };
    }
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

export async function signInWithGoogleAction(): Promise<never> {
  await signIn("google", { redirectTo: "/" });
  redirect("/");
}
