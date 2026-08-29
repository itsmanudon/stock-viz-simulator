import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import HomePage from "@/app/(public)/page";
import { SiteFooter } from "@/components/site-footer";

vi.mock("@/components/top-movers", () => ({
  TopMovers: () => <div>Top movers</div>,
}));

// The hero, ticker, tour, and stat band are async server components that fetch
// live data from the API; each is covered on its own or in the Playwright
// marketing spec. Stub them so HomePage renders synchronously and this suite
// stays on what page.tsx itself owns — the workspace surface index. Stubbing
// the tour also severs the `lib/api/leaderboard` → `@/auth` → next-auth import
// chain, which Vitest cannot resolve.
vi.mock("@/components/marketing/hero", () => ({ Hero: () => <div>Hero</div> }));
vi.mock("@/components/marketing/market-ticker", () => ({
  MarketTicker: () => <div>Market ticker</div>,
}));
vi.mock("@/components/marketing/product-tour", () => ({
  ProductTour: () => <div>Product tour</div>,
}));
vi.mock("@/components/marketing/by-the-numbers", () => ({
  ByTheNumbers: () => <div>By the numbers</div>,
}));
vi.mock("@/components/marketing/closing-cta", () => ({
  ClosingCta: () => <div>Closing CTA</div>,
}));

describe("SiteFooter", () => {
  it("groups destinations into labelled navigation landmarks", () => {
    render(<SiteFooter />);

    for (const heading of ["Research", "Simulation", "Account"]) {
      const nav = screen.getByRole("navigation", { name: heading });
      expect(within(nav).getAllByRole("link").length).toBeGreaterThan(2);
    }
  });

  it("states that trading is simulated on every marketing page", () => {
    render(<SiteFooter />);
    expect(screen.getByText(/not a live brokerage/i)).toBeVisible();
  });
});

describe("HomePage", () => {
  it("links every workspace surface to the route it describes", () => {
    render(<HomePage />);

    for (const [name, href] of [
      ["Markets", "/markets"],
      ["Screener", "/screener"],
      ["Signals", "/recommendations"],
      ["Backtest", "/backtest"],
      ["Paper trading", "/trade"],
      ["Portfolio", "/portfolio"],
    ] as const) {
      expect(screen.getByRole("link", { name })).toHaveAttribute("href", href);
    }
  });
});
