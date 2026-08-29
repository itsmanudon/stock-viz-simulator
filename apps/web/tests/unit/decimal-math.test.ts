import { describe, expect, it } from "vitest";

import { compareDecimalStrings, multiplyDecimalStrings } from "@/lib/decimal-math";

describe("multiplyDecimalStrings", () => {
  it("multiplies quantity and price without binary float drift", () => {
    expect(multiplyDecimalStrings("3", "20", 2)).toBe("60.00");
    expect(multiplyDecimalStrings("0.1", "0.2", 2)).toBe("0.02");
    expect(multiplyDecimalStrings("1.005", "1", 2)).toBe("1.01");
  });

  it("rejects malformed inputs", () => {
    expect(multiplyDecimalStrings("abc", "2")).toBeNull();
    expect(multiplyDecimalStrings("", "2")).toBeNull();
  });
});

describe("compareDecimalStrings", () => {
  it("compares equal scaled zeros", () => {
    expect(compareDecimalStrings("0", "0.00")).toBe(0);
    expect(compareDecimalStrings("2.5", "2.50")).toBe(0);
    expect(compareDecimalStrings("10", "2")).toBe(1);
  });
});
