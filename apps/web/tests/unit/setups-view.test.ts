import { describe, expect, it } from "vitest";

import { screenerHrefForRule, setupsHref } from "@/lib/setups-view";

describe("setups links (A2.2)", () => {
  it("opens a rule in the screener as a shareable link", () => {
    expect(screenerHrefForRule("close > sma(close, 200)")).toBe(
      "/screener?rule=close+%3E+sma%28close%2C+200%29",
    );
    expect(screenerHrefForRule("close > open", "all")).toBe(
      "/screener?rule=close+%3E+open&rule_mode=all",
    );
  });

  it("builds /setups with a setup's versions open or archived shown", () => {
    expect(setupsHref({})).toBe("/setups");
    expect(setupsHref({ open: 4 })).toBe("/setups?open=4");
    expect(setupsHref({ archived: true })).toBe("/setups?archived=1");
  });
});
