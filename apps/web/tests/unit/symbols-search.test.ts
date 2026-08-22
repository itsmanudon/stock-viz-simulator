import { describe, expect, it } from "vitest";

import { searchSymbols } from "@/lib/api/symbols";

describe("searchSymbols", () => {
  it("returns an empty list without calling the API when the query is blank", async () => {
    await expect(searchSymbols("")).resolves.toEqual([]);
    await expect(searchSymbols("   ")).resolves.toEqual([]);
  });
});
