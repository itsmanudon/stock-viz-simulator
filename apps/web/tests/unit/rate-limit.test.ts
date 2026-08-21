import { beforeEach, describe, expect, it, vi } from "vitest";

import { clearAll, hit, reset } from "@/lib/rate-limit";

describe("hit", () => {
  beforeEach(() => {
    clearAll();
    vi.useRealTimers();
  });

  it("allows attempts up to the limit", () => {
    for (let i = 0; i < 5; i++) {
      expect(hit("k", 5, 60_000).allowed).toBe(true);
    }
  });

  it("blocks the attempt after the limit", () => {
    for (let i = 0; i < 5; i++) hit("k", 5, 60_000);
    const result = hit("k", 5, 60_000);
    expect(result.allowed).toBe(false);
    expect(result.retryAfterSeconds).toBeGreaterThan(0);
  });

  it("keys windows independently", () => {
    for (let i = 0; i < 5; i++) hit("alice", 5, 60_000);
    expect(hit("alice", 5, 60_000).allowed).toBe(false);
    // Bob is unaffected — one account under attack must not lock out others.
    expect(hit("bob", 5, 60_000).allowed).toBe(true);
  });

  it("starts a fresh window once the old one expires", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-01-01T00:00:00Z"));

    for (let i = 0; i < 5; i++) hit("k", 5, 60_000);
    expect(hit("k", 5, 60_000).allowed).toBe(false);

    vi.setSystemTime(new Date("2026-01-01T00:01:01Z"));
    expect(hit("k", 5, 60_000).allowed).toBe(true);
  });

  it("reset clears a key so a successful login doesn't leave a user throttled", () => {
    for (let i = 0; i < 5; i++) hit("k", 5, 60_000);
    expect(hit("k", 5, 60_000).allowed).toBe(false);

    reset("k");
    expect(hit("k", 5, 60_000).allowed).toBe(true);
  });
});
