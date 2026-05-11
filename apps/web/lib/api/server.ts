/**
 * Server-only API client for authenticated /v1 endpoints.
 *
 * Reads the NextAuth session via ``auth()``, then calls FastAPI with the
 * shared internal token + user id headers. ``INTERNAL_API_TOKEN`` is a
 * server-side env var — never expose it to the browser.
 *
 * The default fetch base picks the server-side ``API_URL``; the client base
 * (``NEXT_PUBLIC_API_URL``) is irrelevant here since these calls only run
 * server-side.
 */

import "server-only";

import { auth } from "@/auth";

const API_URL = process.env.API_URL ?? "http://127.0.0.1:8000";
const INTERNAL_TOKEN = process.env.INTERNAL_API_TOKEN ?? "";

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

async function authedFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const session = await auth();
  if (!session?.user?.id) throw new UnauthenticatedError();

  const headers = new Headers(init.headers);
  headers.set("X-Internal-Token", INTERNAL_TOKEN);
  headers.set("X-User-Id", session.user.id);
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

export async function authedPost<T>(path: string, body: unknown): Promise<T> {
  const res = await authedFetch(path, { method: "POST", body: JSON.stringify(body) });
  return jsonOrThrow<T>(path, res);
}
