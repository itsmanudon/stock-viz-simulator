import { readdirSync, statSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

import {
  SETTINGS_NAVIGATION,
  UTILITY_NAVIGATION,
  WORKSPACES,
  getActiveNavigation,
  pathMatches,
  workspaceForPath,
  workspaceSubnav,
} from "@/lib/app-navigation";

const PRODUCT_DIR = path.resolve(__dirname, "../../app/(product)");

/** Every `page.tsx` under app/(product), as a URL with sample values for dynamic segments. */
function productRoutes(dir = PRODUCT_DIR, segments: string[] = []): string[] {
  const routes: string[] = [];
  for (const entry of readdirSync(dir)) {
    const full = path.join(dir, entry);
    if (statSync(full).isDirectory()) {
      // Route groups `(name)` add no URL segment; dynamic `[x]` gets a sample value.
      const segment = /^\(.*\)$/.test(entry) ? null : entry.replace(/^\[.*\]$/, "sample");
      routes.push(...productRoutes(full, segment ? [...segments, segment] : segments));
    } else if (entry === "page.tsx") {
      routes.push(`/${segments.join("/")}`);
    }
  }
  return routes;
}

describe("route → workspace map", () => {
  const routes = productRoutes();

  it("finds the product pages", () => {
    expect(routes).toEqual(expect.arrayContaining(["/dashboard", "/stocks/sample", "/copilot"]));
    expect(routes.length).toBeGreaterThan(25);
  });

  it("maps every product page to exactly one workspace or the bottom rail", () => {
    const unmapped = routes.filter((route) => {
      const inRail = UTILITY_NAVIGATION.some((item) => pathMatches(route, item.matches));
      return !inRail && workspaceForPath(route) === null;
    });
    // A new page fails here until it is added to lib/app-navigation.ts.
    expect(unmapped).toEqual([]);
  });

  it.each([
    ["/dashboard", "today", "/dashboard"],
    ["/notifications", "today", "/notifications"],
    ["/markets", "markets", "/markets"],
    ["/earnings", "markets", "/earnings"],
    ["/screener", "markets", "/screener"],
    ["/news", "markets", "/news"],
    ["/stocks/AAPL", "workbench", null],
    ["/stocks/RELIANCE.NS?tf=1Y", "workbench", null],
    ["/compare?tickers=AAPL", "workbench", "/compare"],
    ["/setups", "workbench", "/setups"],
    ["/charts?grid=4&s=AAPL,AAPL,MSFT,TSLA", "workbench", "/charts"],
    ["/checklist", "workbench", "/checklist"],
    ["/recommendations", "workbench", "/checklist"],
    ["/event-study", "workbench", "/event-study"],
    ["/backtest?ticker=AAPL", "quant-lab", "/backtest"],
    ["/backtest/runs", "quant-lab", "/backtest/runs"],
    ["/backtest/runs/12", "quant-lab", "/backtest/runs"],
    ["/replay/42", "quant-lab", "/replay"],
    ["/drills/new", "quant-lab", "/drills"],
    ["/news-reactions", "quant-lab", "/news-reactions"],
    ["/portfolio?tab=journal", "portfolio-tax", "/portfolio"],
    ["/portfolio/journal/42", "portfolio-tax", "/portfolio"],
    ["/trade", "portfolio-tax", "/trade"],
    ["/orders/42", "portfolio-tax", "/orders"],
    ["/trades", "portfolio-tax", "/trades"],
    ["/watchlist", "portfolio-tax", "/watchlist"],
    ["/alerts", "portfolio-tax", "/alerts"],
    ["/copilot", "copilot", "/copilot"],
  ])("maps %s to %s", (pathname, workspaceId, itemHref) => {
    expect(getActiveNavigation(pathname)).toEqual({ workspaceId, itemHref });
  });

  it("does not confuse sibling prefixes", () => {
    expect(pathMatches("/marketplace", ["/markets"])).toBe(false);
    // /trades is not /trade, /news-reactions is not /news.
    expect(getActiveNavigation("/trades").itemHref).toBe("/trades");
    expect(getActiveNavigation("/news-reactions").workspaceId).toBe("quant-lab");
  });

  it("keeps Settings and Status in the bottom rail, outside every workspace", () => {
    expect(getActiveNavigation("/settings")).toEqual({ workspaceId: null, itemHref: "/settings" });
    expect(getActiveNavigation("/status")).toEqual({ workspaceId: null, itemHref: "/status" });
    const hrefs = WORKSPACES.flatMap((w) => w.items.map((item) => item.href));
    expect(hrefs).not.toContain(SETTINGS_NAVIGATION.href);
    expect(getActiveNavigation("/login")).toEqual({ workspaceId: null, itemHref: null });
  });

  it("orders the six workspaces as the architecture does", () => {
    expect(WORKSPACES.map((w) => w.label)).toEqual([
      "Today",
      "Markets",
      "Workbench",
      "Quant Lab",
      "Portfolio & Tax",
      "AI Copilot",
    ]);
    const hrefs = WORKSPACES.flatMap((w) => w.items.map((item) => item.href));
    expect(new Set(hrefs).size).toBe(hrefs.length);
  });

  it("gives each workspace page its own subnav", () => {
    expect(workspaceSubnav("/replay").map((item) => item.label)).toEqual([
      "Backtest",
      "Saved runs",
      "Experiments",
      "Replay",
      "Drills",
      "Classroom",
      "Pairs lab",
      "Optimiser",
      "News reactions",
    ]);
    // Books opens Settings, so it is not a workspace tab.
    expect(workspaceSubnav("/portfolio").map((item) => item.label)).not.toContain("Books");
  });
});
