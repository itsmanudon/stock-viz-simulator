import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PortfolioTabs } from "@/components/portfolio-tabs";

const push = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
}));

describe("portfolio tabs", () => {
  beforeEach(() => {
    push.mockReset();
  });

  it("exposes the selected operational dataset with accessible tab semantics", () => {
    render(
      <PortfolioTabs
        activeTab="positions"
        range="3m"
        positions={<p>Positions panel</p>}
        options={<p>Options panel</p>}
        orders={<p>Orders panel</p>}
        income={<p>Income panel</p>}
        optionCount={2}
        orderCount={1}
      />,
    );

    expect(screen.getByRole("tablist", { name: "Portfolio sections" })).toBeVisible();
    expect(screen.getByRole("tab", { name: "Positions" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: "Options 2" })).toBeVisible();
    expect(screen.getByRole("tab", { name: "Orders 1" })).toBeVisible();
    expect(screen.getByText("Positions panel")).toBeVisible();
  });

  it("updates the URL while preserving the selected performance range", async () => {
    const user = userEvent.setup();
    render(
      <PortfolioTabs
        activeTab="positions"
        range="1y"
        positions={<p>Positions panel</p>}
        options={<p>Options panel</p>}
        orders={<p>Orders panel</p>}
        income={<p>Income panel</p>}
        optionCount={0}
        orderCount={3}
      />,
    );

    await user.click(screen.getByRole("tab", { name: "Orders 3" }));

    expect(push).toHaveBeenCalledWith("/portfolio?range=1y&tab=orders", { scroll: false });
  });

  it("uses the tab keyboard contract to navigate without pointer input", async () => {
    const user = userEvent.setup();
    render(
      <PortfolioTabs
        activeTab="positions"
        range="3m"
        positions={<p>Positions panel</p>}
        options={<p>Options panel</p>}
        orders={<p>Orders panel</p>}
        income={<p>Income panel</p>}
        optionCount={0}
        orderCount={0}
      />,
    );

    const positionsTab = screen.getByRole("tab", { name: "Positions" });
    positionsTab.focus();
    await user.keyboard("{ArrowRight}");

    expect(push).toHaveBeenCalledWith("/portfolio?range=3m&tab=options", { scroll: false });
  });
});
