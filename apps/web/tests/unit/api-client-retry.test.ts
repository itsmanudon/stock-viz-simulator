import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, apiGet } from "@/lib/api/client";

function respond(status: number): Response {
  return new Response(status === 200 ? "{}" : '{"detail":"x"}', { status });
}

describe("apiGet retries (audit RS-6)", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it("does not retry a rate limit: the window answers for every attempt", async () => {
    const fetchMock = vi.fn(async () => respond(429));
    vi.stubGlobal("fetch", fetchMock);

    await expect(apiGet("/v1/screener")).rejects.toBeInstanceOf(ApiError);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("still retries an origin that is starting up", async () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn().mockResolvedValueOnce(respond(503)).mockResolvedValue(respond(200));
    vi.stubGlobal("fetch", fetchMock);

    const pending = apiGet("/v1/symbols");
    await vi.runAllTimersAsync();
    await expect(pending).resolves.toEqual({});
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
