/**
 * Server-only API client for authenticated /v1 endpoints.
 *
 * Reads the NextAuth session via ``auth()``, mints a short-lived HS256 JWT
 * containing the user id, and sends it as ``Authorization: Bearer <token>``.
 * FastAPI verifies the JWT signature with the same ``INTERNAL_API_TOKEN``
 * secret — so neither the user id nor the token itself can be forged by a
 * caller who doesn't know the shared key.
 *
 * ``INTERNAL_API_TOKEN`` is a server-side env var — never expose it to the
 * browser.
 */

import "server-only";

import { SignJWT } from "jose";

import { auth } from "@/auth";
import { requireSecret } from "@/lib/env";

const API_URL = process.env.API_URL ?? "http://127.0.0.1:8000";

export class UnauthenticatedError extends Error {
  constructor() {
    super("Not signed in");
    this.name = "UnauthenticatedError";
  }
}

export class AuthedApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly path: string,
    public readonly detail: string,
  ) {
    super(`API ${status} ${path}: ${detail}`);
    this.name = "AuthedApiError";
  }
}

function signingKey(): Uint8Array {
  // Throws in production if the secret is missing or still the dev default —
  // see lib/env.ts. Read per call so a misconfigured deploy fails on the first
  // authenticated request rather than silently signing with a public key.
  return new TextEncoder().encode(requireSecret("INTERNAL_API_TOKEN"));
}

async function mintToken(userId: string): Promise<string> {
  return new SignJWT({ sub: userId })
    .setProtectedHeader({ alg: "HS256" })
    .setIssuedAt()
    .setExpirationTime("60s")
    .sign(signingKey());
}

async function authedFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const session = await auth();
  if (!session?.user?.id) throw new UnauthenticatedError();

  const token = await mintToken(session.user.id);
  const headers = new Headers(init.headers);
  headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  return fetch(`${API_URL}${path}`, {
    ...init,
    headers,
    cache: "no-store",
  });
}

async function jsonOrThrow<T>(path: string, res: Response): Promise<T> {
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new AuthedApiError(res.status, path, text || res.statusText);
  }
  return (await res.json()) as T;
}

export async function authedGet<T>(path: string): Promise<T> {
  const res = await authedFetch(path, { method: "GET" });
  return jsonOrThrow<T>(path, res);
}

export async function authedPost<T>(path: string, body?: unknown): Promise<T> {
  const init: RequestInit = { method: "POST" };
  if (body !== undefined) init.body = JSON.stringify(body);
  const res = await authedFetch(path, init);
  return jsonOrThrow<T>(path, res);
}

export async function authedPatch<T>(path: string, body?: unknown): Promise<T> {
  const init: RequestInit = { method: "PATCH" };
  if (body !== undefined) init.body = JSON.stringify(body);
  const res = await authedFetch(path, init);
  return jsonOrThrow<T>(path, res);
}

export async function authedDelete(path: string): Promise<void> {
  const res = await authedFetch(path, { method: "DELETE" });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new AuthedApiError(res.status, path, text || res.statusText);
  }
}
