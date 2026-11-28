import { fireEvent, render, screen, within } from "@testing-library/react";
import type React from "react";
import { describe, expect, it, vi } from "vitest";

import HomePage from "@/app/(public)/page";
import { SiteFooter } from "@/components/site-footer";

// The hero and the landing sections are async server components that fetch
// live data from the API; each is covered on its own or in the Playwright
// marketing spec. Stub them so HomePage renders synchronously and this suite
// stays on what page.tsx itself owns — the workspace surface index. Stubbing
// the sections also severs the `lib/api/*` → `@/auth` → next-auth
// import chain, which Vitest cannot resolve. LandingMotion is stubbed because
// GSAP's matchMedia needs `window.matchMedia`, which jsdom does not provide.
vi.mock("@/components/marketing/hero", () => ({ Hero: () => <div>Hero</div> }));
vi.mock("@/components/marketing/landing-motion", () => ({
  LandingMotion: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));
vi.mock("@/components/marketing/landing-sections", () => ({
  MovingToday: () => <div>Moving today</div>,
  SessionTiles: () => <div>Session tiles</div>,
  StorySection: () => <div>Scroll story</div>,
  FillSteps: () => <div>Fill steps</div>,
  StatementBand: () => <div>Statement band</div>,
  LandingFaq: () => <div>FAQ</div>,
}));
vi.mock("@/components/marketing/proofs/proof-section", () => ({
  ProofSection: () => <div>Watch it work</div>,
}));
// PRISM sections: the terrain loads market data (async server component).
vi.mock("@/components/prism/terrain-section", () => ({
  TerrainSection: () => <div>Terrain</div>,
}));
vi.mock("@/components/marketing/closing-cta", () => ({
  ClosingCta: () => <div>Closing CTA</div>,
}));

// The footer's close line and status strip are async server components over
// the API; the pure parts are covered in footer-market.test.ts.
vi.mock("@/components/footer-market", () => ({
  FooterCloseLine: () => null,
  FooterStatus: () => null,
}));

describe("SiteFooter", () => {
  it("links no source repository while the project is private, and shows the package version", () => {
    render(<SiteFooter />);
    expect(screen.queryByRole("link", { name: /github/i })).toBeNull();
    expect(screen.getByText(/StockViz · v2\.0\.0-alpha/)).toBeVisible();
  });

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
  it("visits every workspace surface as a stop and links it to its route", () => {
    render(<HomePage />);

    for (const [index, name, href] of [
      [1, "Markets", "/markets"],
      [2, "Screener", "/screener"],
      [3, "Checklist", "/checklist"],
      [4, "Backtest", "/backtest"],
      [5, "Paper trading", "/trade"],
      [6, "Portfolio", "/portfolio"],
    ] as const) {
      fireEvent.click(screen.getByRole("button", { name: `Stop ${index}: ${name}` }));
      expect(screen.getByText(`Stop ${index} of 6`)).toBeInTheDocument();
      expect(screen.getByRole("link", { name: `Open ${name}` })).toHaveAttribute("href", href);
    }

    fireEvent.click(screen.getByRole("button", { name: "Next stop" }));
    expect(screen.getByText("Stop 1 of 6")).toBeInTheDocument();
  });
});
