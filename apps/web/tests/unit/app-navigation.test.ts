import { describe, expect, it } from "vitest";

import { APP_NAVIGATION, getActiveNavigation, pathMatches } from "@/lib/app-navigation";

describe("pathMatches", () => {
  it("matches a route and its descendants without matching a sibling prefix", () => {
    expect(pathMatches("/stocks/AAPL", ["/stocks"])).toBe(true);
    expect(pathMatches("/marketplace", ["/markets"])).toBe(false);
  });
});

describe("getActiveNavigation", () => {
  it.each([
    ["/dashboard", "/dashboard", "/dashboard"],
    ["/markets", "/markets", "/markets"],
    ["/stocks/AAPL", "/screener", null],
    ["/compare?tickers=AAPL", "/screener", "/compare"],
    ["/backtest", "/trade", "/backtest"],
    ["/orders/42", "/trade", "/orders"],
    ["/watchlist", "/portfolio", "/watchlist"],
    ["/trades", "/portfolio", "/trades"],
    ["/leaderboard", "/leaderboard", "/leaderboard"],
  ])("maps %s to its owning domain", (pathname, groupHref, itemHref) => {
    expect(getActiveNavigation(pathname)).toEqual({ groupHref, itemHref });
  });

  it("returns no active route for public pages", () => {
    expect(getActiveNavigation("/login")).toEqual({ groupHref: null, itemHref: null });
  });

  it("defines six top-level product domains", () => {
    expect(APP_NAVIGATION.map((group) => group.label)).toEqual([
      "Home",
      "Markets",
      "Research",
      "Trade",
      "Portfolio",
      "Community",
    ]);
  });
});
