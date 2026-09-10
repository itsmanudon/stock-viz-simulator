import { render, screen, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import HomePage from "@/app/(public)/page";
import { SiteFooter } from "@/components/site-footer";

// Keep server data sections out of JSDOM; Playwright covers their real output.
vi.mock("@/components/marketing/hero", () => ({ Hero: () => null }));
vi.mock("@/components/marketing/market-ticker", () => ({ MarketTicker: () => null }));
vi.mock("@/components/marketing/product-tour", () => ({ ProductTour: () => null }));
vi.mock("@/components/marketing/by-the-numbers", () => ({ ByTheNumbers: () => null }));
vi.mock("@/components/marketing/reveal", () => ({
  Reveal: ({ children }: { children: ReactNode }) => <div>{children}</div>,
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
  it("offers a signup call to action", () => {
    render(<HomePage />);

    expect(screen.getAllByRole("link", { name: /Create free account/ })[0]).toHaveAttribute(
      "href",
      "/signup",
    );
  });

  it("links every feature to the route it describes", () => {
    render(<HomePage />);

    for (const [name, href] of [
      ["Markets", "/markets"],
      ["Screener", "/screener"],
      ["Signals", "/recommendations"],
      ["Backtest", "/backtest"],
      ["Paper trading", "/trade"],
      ["Portfolio", "/portfolio"],
    ] as const) {
      expect(screen.getByRole("link", { name: new RegExp(name) })).toHaveAttribute("href", href);
    }
  });

  it("does not oversell the simulator as live trading", () => {
    render(<HomePage />);
    expect(screen.getByRole("heading", { name: /Start with.*100,000.*isn.t real/i })).toBeVisible();
  });
});
