import { afterEach, expect, it, vi } from "vitest";

import { type LeaderboardEntry, getLeaderboard } from "@/lib/api/leaderboard";

vi.mock("@/lib/api/server", () => ({ authedGet: vi.fn(), authedPatch: vi.fn() }));

afterEach(() => vi.unstubAllGlobals());

it("never caches leaderboard identities, including calls with a legacy TTL argument", async () => {
  const entries: LeaderboardEntry[] = [
    { rank: 1, user_id: 7, username: "Trader", return_pct: 5, portfolio_value: "105000" },
  ];
  const fetchRequest = vi
    .fn()
    .mockResolvedValueOnce(new Response(JSON.stringify(entries), { status: 200 }))
    .mockResolvedValueOnce(new Response("[]", { status: 200 }));
  vi.stubGlobal("fetch", fetchRequest);

  // A deployed JS caller may still supply the old marketing-page TTL.
  const legacyCaller = getLeaderboard as (ttl?: number) => Promise<LeaderboardEntry[]>;
  expect(await legacyCaller(3600)).toEqual(entries);
  expect(await getLeaderboard()).toEqual([]);
  expect(fetchRequest).toHaveBeenCalledTimes(2);
  for (const [url, options] of fetchRequest.mock.calls) {
    expect(url).toMatch(/\/v1\/leaderboard$/);
    expect(options.cache).toBe("no-store");
    expect(options.next).toBeUndefined();
  }
});
