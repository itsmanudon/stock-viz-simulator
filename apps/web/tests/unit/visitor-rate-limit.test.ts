// @vitest-environment node
/**
 * RS-6 option 1: the web server proves itself to the API and limits each
 * visitor by address on the query-driven research pages.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const requestHeaders = new Headers();
vi.mock("next/headers", () => ({ headers: async () => requestHeaders }));

import { apiGet } from "@/lib/api/client";
import { clearAll } from "@/lib/rate-limit";
import { VISITOR_LIMITS, checkVisitorLimit, visitorAddress } from "@/lib/visitor-limit";
import { WEB_SERVER_KEY_SLOT, registerWebServerKey, webServerKey } from "@/lib/web-server-key";

function visitFrom(address: string): void {
  requestHeaders.set("x-forwarded-for", address);
}

describe("web server key", () => {
  afterEach(() => {
    delete (globalThis as Record<symbol, unknown>)[WEB_SERVER_KEY_SLOT];
    vi.unstubAllGlobals();
  });

  it("matches the API's HMAC for the same secret", () => {
    // Vector from apps/api: stockviz.limiter.web_server_key("dev-internal-token-change-me").
    expect(webServerKey("dev-internal-token-change-me")).toBe(
      "30c3ee009f493dad094e947cf55a491c01c473c7dbae6c3621a2b124a8528b3b",
    );
  });

  it("is sent on server-side API calls once registered", async () => {
    registerWebServerKey();
    const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) => new Response("{}"));
    vi.stubGlobal("fetch", fetchMock);

    await apiGet("/v1/screener");

    const sent = new Headers(fetchMock.mock.calls[0][1]?.headers);
    expect(sent.get("X-StockViz-Web")).toBe(webServerKey("dev-internal-token-change-me"));
  });

  it("is not sent when nothing registered it", async () => {
    const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) => new Response("{}"));
    vi.stubGlobal("fetch", fetchMock);

    await apiGet("/v1/screener");

    expect(new Headers(fetchMock.mock.calls[0][1]?.headers).has("X-StockViz-Web")).toBe(false);
  });
});

describe("visitorAddress", () => {
  it("takes the left-most forwarded address", () => {
    expect(visitorAddress(new Headers({ "x-forwarded-for": "203.0.113.5, 10.0.0.1" }))).toBe(
      "203.0.113.5",
    );
  });

  it("falls back to x-real-ip, then to one shared key", () => {
    expect(visitorAddress(new Headers({ "x-real-ip": "203.0.113.6" }))).toBe("203.0.113.6");
    expect(visitorAddress(new Headers())).toBe("unknown");
  });
});

describe("checkVisitorLimit", () => {
  beforeEach(() => {
    clearAll();
    requestHeaders.delete("x-forwarded-for");
  });

  it("throttles a burst from one visitor and not another", async () => {
    visitFrom("203.0.113.10");
    for (let i = 0; i < VISITOR_LIMITS.screener; i++) {
      expect((await checkVisitorLimit("screener")).allowed).toBe(true);
    }
    const blocked = await checkVisitorLimit("screener");
    expect(blocked.allowed).toBe(false);
    expect(blocked.retryAfterSeconds).toBeGreaterThan(0);

    visitFrom("203.0.113.11");
    expect((await checkVisitorLimit("screener")).allowed).toBe(true);
  });

  it("counts each page on its own", async () => {
    visitFrom("203.0.113.12");
    for (let i = 0; i <= VISITOR_LIMITS.compare; i++) await checkVisitorLimit("compare");
    expect((await checkVisitorLimit("compare")).allowed).toBe(false);
    expect((await checkVisitorLimit("stock")).allowed).toBe(true);
  });
});
