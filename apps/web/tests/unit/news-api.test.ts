import { beforeEach, describe, expect, it, vi } from "vitest";

const apiGet = vi.fn();
vi.mock("@/lib/api/client", () => ({ apiGet: (...args: unknown[]) => apiGet(...args) }));

import { getNewsForTickers } from "@/lib/api/news";

describe("getNewsForTickers (Phase 2)", () => {
  beforeEach(() => {
    apiGet.mockReset();
    apiGet.mockResolvedValue([]);
  });

  it("asks once for the whole set, sorted and de-duplicated so the cache key is stable", async () => {
    await getNewsForTickers(["msft", " AAPL", "MSFT", ""], 10);
    expect(apiGet).toHaveBeenCalledTimes(1);
    expect(apiGet.mock.calls[0][0]).toBe("/v1/news?tickers=AAPL%2CMSFT&limit=10");
  });

  it("makes no request for an empty list", async () => {
    await expect(getNewsForTickers([])).resolves.toEqual([]);
    expect(apiGet).not.toHaveBeenCalled();
  });
});
