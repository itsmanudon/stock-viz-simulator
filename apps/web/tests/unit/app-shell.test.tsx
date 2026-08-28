import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AppMobileNav } from "@/components/app-mobile-nav";
import { AppShell } from "@/components/app-shell";
import { AppSidebar } from "@/components/app-sidebar";
import { PublicHeader } from "@/components/public-header";

let pathname = "/compare";

vi.mock("next/navigation", () => ({
  usePathname: () => pathname,
  useRouter: () => ({ push: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("@/components/account-menu", () => ({
  AccountMenu: () => <button type="button">Account menu</button>,
}));

vi.mock("@/components/alerts-bell", () => ({
  AlertsBell: () => <button type="button">Alerts</button>,
}));

vi.mock("@/auth", () => ({
  auth: vi.fn().mockResolvedValue(null),
}));

describe("AppSidebar", () => {
  it("groups product destinations and marks both the active domain and route", () => {
    render(<AppSidebar signedIn />);
    const nav = screen.getByRole("navigation", { name: "Product" });

    expect(within(nav).getByRole("link", { name: "Research" })).toHaveAttribute(
      "data-active",
      "true",
    );
    expect(within(nav).getByRole("link", { name: "Compare" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(within(nav).getByText("EOD data")).toBeVisible();
  });
});

describe("AppSidebar home link", () => {
  it("keeps signed-out visitors on the marketing home instead of the sign-in wall", () => {
    render(<AppSidebar signedIn={false} />);
    const nav = screen.getByRole("navigation", { name: "Product" });

    expect(within(nav).getByRole("link", { name: "Home" })).toHaveAttribute("href", "/");
  });

  it("points signed-in users at the dashboard", () => {
    render(<AppSidebar signedIn />);
    const nav = screen.getByRole("navigation", { name: "Product" });

    expect(within(nav).getByRole("link", { name: "Home" })).toHaveAttribute("href", "/dashboard");
  });
});

describe("AppMobileNav", () => {
  beforeEach(() => {
    pathname = "/markets";
  });

  it("opens an accessible drawer and closes on Escape", () => {
    render(<AppMobileNav signedIn />);

    fireEvent.click(screen.getByRole("button", { name: "Open navigation" }));
    expect(screen.getByRole("dialog", { name: "Product navigation" })).toBeVisible();

    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "Product navigation" })).not.toBeInTheDocument();
  });

  it("closes after selecting a destination", () => {
    render(<AppMobileNav signedIn />);

    fireEvent.click(screen.getByRole("button", { name: "Open navigation" }));
    const destination = screen.getByRole("link", { name: "Screener" });
    destination.addEventListener("click", (event) => event.preventDefault(), { once: true });
    fireEvent.click(destination);

    expect(screen.queryByRole("dialog", { name: "Product navigation" })).not.toBeInTheDocument();
  });
});

describe("AppShell", () => {
  it("renders the workstation main landmark and utilities without a website footer", () => {
    render(
      <AppShell signedIn>
        <h1>Markets</h1>
      </AppShell>,
    );

    expect(screen.getByRole("main")).toHaveAttribute("id", "main");
    expect(screen.getByRole("combobox", { name: "Search tickers and companies" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Alerts" })).toBeVisible();
    expect(screen.queryByRole("contentinfo")).not.toBeInTheDocument();
  });
});

describe("PublicHeader", () => {
  it("keeps marketing navigation concise", async () => {
    render(await PublicHeader());
    const nav = screen.getByRole("navigation", { name: "Public" });

    expect(within(nav).getAllByRole("link")).toHaveLength(3);
    expect(screen.queryByRole("link", { name: "Orders" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Create account" })).toHaveAttribute("href", "/signup");
  });
});
