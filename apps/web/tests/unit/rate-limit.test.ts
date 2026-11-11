import { beforeEach, describe, expect, it, vi } from "vitest";

import { clearAll, hit, reset } from "@/lib/rate-limit";

async function hits(key: string, times: number): Promise<void> {
  for (let i = 0; i < times; i++) await hit(key, 5, 60_000);
}

describe("hit", () => {
  beforeEach(() => {
    clearAll();
    vi.useRealTimers();
  });

  it("allows attempts up to the limit", async () => {
    for (let i = 0; i < 5; i++) {
      expect((await hit("k", 5, 60_000)).allowed).toBe(true);
    }
  });

  it("blocks the attempt after the limit", async () => {
    await hits("k", 5);
    const result = await hit("k", 5, 60_000);
    expect(result.allowed).toBe(false);
    expect(result.retryAfterSeconds).toBeGreaterThan(0);
  });

  it("keys windows independently", async () => {
    await hits("alice", 5);
    expect((await hit("alice", 5, 60_000)).allowed).toBe(false);
    // Bob is unaffected — one account under attack must not lock out others.
    expect((await hit("bob", 5, 60_000)).allowed).toBe(true);
  });

  it("starts a fresh window once the old one expires", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-01-01T00:00:00Z"));

    await hits("k", 5);
    expect((await hit("k", 5, 60_000)).allowed).toBe(false);

    vi.setSystemTime(new Date("2026-01-01T00:01:01Z"));
    expect((await hit("k", 5, 60_000)).allowed).toBe(true);
  });

  it("reset clears a key so a successful login doesn't leave a user throttled", async () => {
    await hits("k", 5);
    expect((await hit("k", 5, 60_000)).allowed).toBe(false);

    await reset("k");
    expect((await hit("k", 5, 60_000)).allowed).toBe(true);
  });
});
