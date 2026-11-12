import { describe, expect, it, vi } from "vitest";

const revalidated: [string, unknown][] = [];
vi.mock("next/cache", () => ({
  revalidateTag: (tag: string, profile: unknown) => revalidated.push([tag, profile]),
}));
vi.mock("@/lib/env", () => ({ requireSecret: () => "test-secret" }));

import { POST } from "@/app/api/revalidate/route";
import { MARKET_TAGS, revalidateKey } from "@/lib/revalidate-key";

// Same value as the API's `stockviz.cli.revalidate_key("test-secret")`
// (tests/test_revalidate_web.py pins it there too).
const KEY = "d5a8aaaaca52b715f19a726eef34f3409b1a8f3cf8efc86156a42b71d398eb85";

describe("POST /api/revalidate (audit RS-9)", () => {
  it("computes the same key as the API", () => {
    expect(revalidateKey("test-secret")).toBe(KEY);
  });

  it("refuses a missing or wrong key and changes nothing", async () => {
    revalidated.length = 0;
    const wrong = await POST(
      new Request("http://web/api/revalidate", {
        method: "POST",
        headers: { "x-stockviz-revalidate": "nope" },
      }),
    );
    expect(wrong.status).toBe(401);
    expect(revalidated).toEqual([]);
  });

  it("drops every market tag at once (no stale serve)", async () => {
    revalidated.length = 0;
    const ok = await POST(
      new Request("http://web/api/revalidate", {
        method: "POST",
        headers: { "x-stockviz-revalidate": KEY },
      }),
    );
    expect(ok.status).toBe(200);
    expect(revalidated.map(([t]) => t)).toEqual([...MARKET_TAGS]);
    expect(revalidated.every(([, p]) => JSON.stringify(p) === '{"expire":0}')).toBe(true);
  });
});
