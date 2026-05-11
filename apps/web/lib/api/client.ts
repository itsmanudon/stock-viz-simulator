/**
 * Tiny fetch wrapper for the FastAPI backend.
 *
 * Server components: the API base URL comes from API_URL (server-side env).
 * Client components: NEXT_PUBLIC_API_URL is exposed at build time.
 *
 * We deliberately keep this dumb — no retries, no auth header yet. Auth gets
 * threaded through in Phase 6 when the FastAPI side starts verifying JWTs.
 */

const SERVER_BASE = process.env.API_URL ?? "http://127.0.0.1:8000";
const BROWSER_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

function baseUrl(): string {
  return typeof window === "undefined" ? SERVER_BASE : BROWSER_BASE;
}

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly path: string,
    message: string,
  ) {
    super(`API ${status} ${path}: ${message}`);
    this.name = "ApiError";
  }
}

type FetchOpts = {
  /** Forwarded to fetch's RequestInit. */
  init?: RequestInit;
  /**
   * Next.js fetch cache control. Default ``no-store`` so server components
   * always see fresh data — flip to a revalidate window per-call when caching
   * makes sense.
   */
  cache?: RequestCache;
};

export async function apiGet<T>(path: string, opts: FetchOpts = {}): Promise<T> {
  const url = `${baseUrl()}${path}`;
  const res = await fetch(url, {
    ...opts.init,
    method: "GET",
    cache: opts.cache ?? "no-store",
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new ApiError(res.status, path, detail || res.statusText);
  }
  return (await res.json()) as T;
}
