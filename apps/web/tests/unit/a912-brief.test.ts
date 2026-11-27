/** A9.12 (M11.6): brief and weekly review helpers. */
import { describe, expect, it } from "vitest";

import { WORKSPACES } from "@/lib/app-navigation";
import { moveText, shiftWeek, weekHref } from "@/lib/brief";

describe("brief helpers", () => {
  it("formats moves with their sign", () => {
    expect(moveText(3)).toBe("+3.00%");
    expect(moveText(-1.234)).toBe("-1.23%");
    expect(moveText(0)).toBe("0.00%");
  });

  it("steps weeks across month and year ends", () => {
    expect(shiftWeek("2026-11-27", 7)).toBe("2026-12-04");
    expect(shiftWeek("2027-01-03", -7)).toBe("2026-12-27");
    expect(weekHref("2026-11-27", "4")).toBe("/portfolio/journal/week?week_end=2026-11-27&book=4");
    expect(weekHref("2026-11-27")).toBe("/portfolio/journal/week?week_end=2026-11-27");
  });

  it("puts the Morning Brief in Today, signed in only", () => {
    const today = WORKSPACES.find((w) => w.id === "today");
    const item = today?.items.find((i) => i.href === "/brief");
    expect(item?.label).toBe("Morning Brief");
    expect(item && "signedInOnly" in item ? item.signedInOnly : false).toBe(true);
  });
});
