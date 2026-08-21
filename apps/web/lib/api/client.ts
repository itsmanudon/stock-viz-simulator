/**
 * Fetch wrapper for the FastAPI backend.
 *
 * Server components: the API base URL comes from API_URL (server-side env).
 * Client components: NEXT_PUBLIC_API_URL is exposed at build time.
 *
 * Two behaviours matter in production. The API runs on Render's free tier,
 * which spins down after ~15 minutes idle and takes 30-60s to cold start — so
 * transient 502/503/504s and connection resets are normal, and we retry them
 * with backoff rather than surfacing an error page. And EOD data changes once
 * a day, so callers can opt into Next's data cache with `revalidateSeconds`
 * instead of every request going to the origin.
 */

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

const SERVER_BASE = process.env.API_URL ?? "http://127.0.0.1:8000";
const BROWSER_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

function baseUrl(): string {
  return typeof window === "undefined" ? SERVER_BASE : BROWSER_BASE;
}

/** Statuses worth retrying: the origin is starting up or briefly overloaded. */
const RETRYABLE_STATUSES = new Set([408, 425, 429, 500, 502, 503, 504]);

const MAX_ATTEMPTS = 3;
const BASE_DELAY_MS = 400;

export type FetchOpts = {
  /** Forwarded to fetch's RequestInit. */
  init?: RequestInit;
  /**
   * Next.js fetch cache control. Defaults to `no-store` so server components
   * see fresh data. Prefer `revalidateSeconds` for data that changes daily.
   */
  cache?: RequestCache;
  /** Cache the response for N seconds (Next data cache). Overrides `cache`. */
  revalidateSeconds?: number;
  /** Cache tags, so a mutation can call revalidateTag() to bust this entry. */
  tags?: string[];
  /** Set to 0 to disable retries (e.g. for a request the user is waiting on). */
  maxAttempts?: number;
};

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function nextOptions(opts: FetchOpts): RequestInit {
  if (opts.revalidateSeconds === undefined && !opts.tags) {
    return { cache: opts.cache ?? "no-store" };
  }
  return {
    next: {
      ...(opts.revalidateSeconds !== undefined ? { revalidate: opts.revalidateSeconds } : {}),
      ...(opts.tags ? { tags: opts.tags } : {}),
    },
  };
}

async function request<T>(path: string, init: RequestInit, opts: FetchOpts): Promise<T> {
  const url = `${baseUrl()}${path}`;
  const attempts = opts.maxAttempts ?? MAX_ATTEMPTS;
  let lastError: unknown;

  for (let attempt = 1; attempt <= attempts; attempt++) {
    let res: Response;
    try {
      res = await fetch(url, { ...init, ...nextOptions(opts) });
    } catch (err) {
      // Network-level failure (connection refused, DNS, reset) — the shape a
      // cold-starting origin produces most often.
      lastError = err;
      if (attempt === attempts) break;
      await sleep(BASE_DELAY_MS * 2 ** (attempt - 1));
      continue;
    }

    if (res.ok) return (await res.json()) as T;

    const detail = await res.text().catch(() => "");
    lastError = new ApiError(res.status, path, detail || res.statusText);
    if (!RETRYABLE_STATUSES.has(res.status) || attempt === attempts) break;
    await sleep(BASE_DELAY_MS * 2 ** (attempt - 1));
  }

  if (lastError instanceof ApiError) throw lastError;
  throw new ApiError(503, path, lastError instanceof Error ? lastError.message : "Request failed");
}

export async function apiGet<T>(path: string, opts: FetchOpts = {}): Promise<T> {
  return request<T>(path, { ...opts.init, method: "GET" }, opts);
}

export async function apiPost<T>(path: string, body: unknown, opts: FetchOpts = {}): Promise<T> {
  const headers = new Headers(opts.init?.headers);
  headers.set("Content-Type", "application/json");
  // Writes are not retried by default: a POST that timed out may still have
  // been applied server-side, and replaying it could duplicate a trade.
  return request<T>(
    path,
    { ...opts.init, method: "POST", headers, body: JSON.stringify(body) },
    { ...opts, maxAttempts: opts.maxAttempts ?? 1 },
  );
}
