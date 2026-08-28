import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import HomePage from "@/app/(public)/page";
import { SiteFooter } from "@/components/site-footer";

vi.mock("@/components/top-movers", () => ({
  TopMovers: () => <div>Top movers</div>,
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
  it("leads with a signup call to action and a way to look around first", () => {
    render(<HomePage />);

    expect(screen.getAllByRole("link", { name: /Create free account/ })[0]).toHaveAttribute(
      "href",
      "/signup",
    );
    expect(screen.getByRole("link", { name: "Explore markets" })).toHaveAttribute(
      "href",
      "/markets",
    );
  });

  it("links every feature to the route it describes", () => {
    render(<HomePage />);

    for (const [name, href] of [
      ["Markets at a glance", "/markets"],
      ["Screen on what matters", "/screener"],
      ["Rule-based signals", "/recommendations"],
      ["Backtest a thesis", "/backtest"],
      ["Paper trade for real", "/trade"],
      ["Track the outcome", "/portfolio"],
    ] as const) {
      expect(screen.getByRole("link", { name: new RegExp(name) })).toHaveAttribute("href", href);
    }
  });

  it("does not oversell the simulator as live trading", () => {
    render(<HomePage />);
    expect(screen.getByText(/not a live brokerage/i)).toBeVisible();
  });
});
