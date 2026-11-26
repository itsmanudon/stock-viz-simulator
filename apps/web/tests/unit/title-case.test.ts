import { describe, expect, it } from "vitest";

import { titleCase } from "@/lib/title-case";

describe("titleCase", () => {
  it("capitalises every word and keeps minor words lower inside a label", () => {
    expect(titleCase("last close")).toBe("Last Close");
    expect(titleCase("return vs hold")).toBe("Return vs Hold");
    expect(titleCase("sign in to save screens")).toBe("Sign In to Save Screens");
    expect(titleCase("or continue with")).toBe("Or Continue With");
  });

  it("keeps tickers, codes and financial abbreviations as written", () => {
    expect(titleCase("realized P&L · USD")).toBe("Realized P&L · USD");
    expect(titleCase("AAPL on NASDAQ")).toBe("AAPL on NASDAQ");
    expect(titleCase("max P/E")).toBe("Max P/E");
    expect(titleCase("RSI (14)")).toBe("RSI (14)");
    expect(titleCase("time (UTC)")).toBe("Time (UTC)");
    expect(titleCase("VaR and CVaR")).toBe("VaR and CVaR");
    expect(titleCase("EOD · simulated")).toBe("EOD · Simulated");
  });

  it("handles hyphens, units and separators", () => {
    expect(titleCase("52-week range")).toBe("52-Week Range");
    expect(titleCase("buy-and-hold excess")).toBe("Buy-and-Hold Excess");
    expect(titleCase("market cap USD bn")).toBe("Market Cap USD bn");
    expect(titleCase("paper account · in progress")).toBe("Paper Account · In Progress");
  });

  it("passes empty values through", () => {
    expect(titleCase("")).toBe("");
    expect(titleCase(null)).toBeNull();
    expect(titleCase(undefined)).toBeUndefined();
  });
});
