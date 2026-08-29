import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import ProductLayout from "@/app/(product)/layout";
import PublicLayout from "@/app/(public)/layout";

vi.mock("@/auth", () => ({
  auth: vi.fn().mockResolvedValue(null),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/markets",
  useRouter: () => ({ push: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("@/components/account-menu", () => ({
  AccountMenu: () => <button type="button">Account</button>,
}));

vi.mock("@/components/alerts-bell", () => ({
  AlertsBell: () => null,
}));

vi.mock("@/components/theme-toggle", () => ({
  ThemeToggle: () => <button type="button">Theme</button>,
}));

vi.mock("@/components/public-header", () => ({
  PublicHeader: () => <header>Public header</header>,
}));

describe("route shell ownership", () => {
  it("renders public content with the website footer", async () => {
    render(
      await PublicLayout({
        children: <h1>Welcome</h1>,
      }),
    );

    expect(screen.getByRole("main")).toHaveAttribute("id", "main");
    expect(screen.getByRole("contentinfo")).toBeVisible();
  });

  it("renders product content with workstation navigation and no footer", async () => {
    render(
      await ProductLayout({
        children: <h1>Markets</h1>,
      }),
    );

    expect(screen.getByRole("navigation", { name: "Product" })).toBeVisible();
    expect(screen.getByRole("main")).toHaveAttribute("id", "main");
    expect(screen.queryByRole("contentinfo")).not.toBeInTheDocument();
  });
});
