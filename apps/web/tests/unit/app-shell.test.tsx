import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AppMobileNav } from "@/components/app-mobile-nav";
import { AppSidebar } from "@/components/app-sidebar";

let pathname = "/compare";

vi.mock("next/navigation", () => ({
  usePathname: () => pathname,
}));

describe("AppSidebar", () => {
  it("groups product destinations and marks both the active domain and route", () => {
    render(<AppSidebar />);
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

describe("AppMobileNav", () => {
  beforeEach(() => {
    pathname = "/markets";
  });

  it("opens an accessible drawer and closes on Escape", () => {
    render(<AppMobileNav />);

    fireEvent.click(screen.getByRole("button", { name: "Open navigation" }));
    expect(screen.getByRole("dialog", { name: "Product navigation" })).toBeVisible();

    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "Product navigation" })).not.toBeInTheDocument();
  });

  it("closes after selecting a destination", () => {
    render(<AppMobileNav />);

    fireEvent.click(screen.getByRole("button", { name: "Open navigation" }));
    const destination = screen.getByRole("link", { name: "Screener" });
    destination.addEventListener("click", (event) => event.preventDefault(), { once: true });
    fireEvent.click(destination);

    expect(screen.queryByRole("dialog", { name: "Product navigation" })).not.toBeInTheDocument();
  });
});
