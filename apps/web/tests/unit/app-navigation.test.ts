import { describe, expect, it } from "vitest";

import {
  APP_NAVIGATION,
  SETTINGS_NAVIGATION,
  getActiveNavigation,
  pathMatches,
} from "@/lib/app-navigation";

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
    ["/backtest?ticker=AAPL", "/screener", "/backtest"],
    ["/recommendations", "/screener", "/recommendations"],
    ["/replay/42", "/screener", "/replay"],
    ["/orders/42", "/trade", "/orders"],
    ["/watchlist", "/portfolio", "/watchlist"],
    ["/alerts", "/portfolio", "/alerts"],
    ["/trades", "/portfolio", "/trades"],
    ["/leaderboard", "/leaderboard", "/leaderboard"],
    ["/settings", "/settings", "/settings"],
  ])("maps %s to its owning domain", (pathname, groupHref, itemHref) => {
    expect(getActiveNavigation(pathname)).toEqual({ groupHref, itemHref });
  });

  it("returns no active route for public pages", () => {
    expect(getActiveNavigation("/login")).toEqual({ groupHref: null, itemHref: null });
  });

  it("orders the sidebar as the Aurora board does", () => {
    expect(APP_NAVIGATION.map((group) => group.label)).toEqual([
      "Home",
      "Markets",
      "Earnings",
      "Research",
      "Trade",
      "Portfolio",
      "Community",
    ]);
    const research = APP_NAVIGATION.find((group) => group.label === "Research");
    expect(research?.href).toBe("/screener");
    expect(research?.items?.map((item) => item.label)).toEqual([
      "Screener",
      "Signals",
      "Compare",
      "Backtest",
      "Replay",
      "News",
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

describe("SETTINGS_NAVIGATION", () => {
  it("is kept out of the grouped sections", () => {
    expect(SETTINGS_NAVIGATION.href).toBe("/settings");
    const hrefs = APP_NAVIGATION.flatMap((group) => [
      group.href,
      ...(group.items?.map((item) => item.href) ?? []),
    ]);
    expect(hrefs).not.toContain("/settings");
  });
});
