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
    ["/stocks/AAPL", "/compare", null],
    ["/compare?tickers=AAPL", "/compare", "/compare"],
    ["/backtest?ticker=AAPL", "/compare", "/backtest"],
    ["/replay", "/compare", "/replay"],
    ["/replay/12", "/compare", "/replay"],
    ["/recommendations", "/compare", "/recommendations"],
    ["/orders/42", "/trade", "/orders"],
    ["/watchlist", "/portfolio", "/watchlist"],
    ["/alerts", "/portfolio", "/alerts"],
    ["/trades", "/portfolio", "/trades"],
    ["/leaderboard", "/leaderboard", "/leaderboard"],
  ])("maps %s to its owning domain", (pathname, groupHref, itemHref) => {
    expect(getActiveNavigation(pathname)).toEqual({ groupHref, itemHref });
  });

  it("returns no active route for public pages", () => {
    expect(getActiveNavigation("/login")).toEqual({ groupHref: null, itemHref: null });
  });

  it("places Compare, Backtest, and Signals under Research", () => {
    const research = APP_NAVIGATION.find((group) => group.label === "Research");
    expect(research?.href).toBe("/compare");
    expect(research?.items?.map((item) => item.label)).toEqual([
      "Compare",
      "Backtest",
      "Signals",
      "Screener",
      "News",
      "Replay",
    ]);
    const trade = APP_NAVIGATION.find((group) => group.label === "Trade");
    expect(trade?.items?.map((item) => item.label)).not.toContain("Backtest");
    const portfolio = APP_NAVIGATION.find((group) => group.label === "Portfolio");
    expect(portfolio?.items?.map((item) => item.label)).toEqual([
      "Overview",
      "Watchlist",
      "Alerts",
      "Trade history",
    ]);
  });
});
