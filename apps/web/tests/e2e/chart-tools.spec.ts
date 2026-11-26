import { expect, test } from "@playwright/test";

import { rightClickChart } from "./chart-helpers";

// A6.7: the volume profile switch and the price pane's context menu (alerts
// and plans), on the seeded daily bars (no minutes: an EOD approximation).

test.describe.configure({ retries: 0 });

// The signed-in half (a price alert and a plan from the menu) runs in
// stock-workspace.spec.ts's authenticated test: signups are throttled per
// address, so the suite adds no signup of its own.

test("a guest turns on the visible-range volume profile and gets a sign-in link", async ({
  page,
}) => {
  await page.goto("/stocks/AAPL");
  const toggle = page.getByTestId("volume-profile-toggle");
  await toggle.getByRole("button", { name: "Volume profile: Visible range" }).click();
  await expect(page).toHaveURL(/vp=visible/);
  await expect(toggle).toHaveAttribute("data-mode", "visible");
  const info = page.getByTestId("volume-profile-info");
  await expect(info.getByTestId("volume-profile-badge").first()).toHaveText("EOD approximation");
  await expect(info.getByTestId("volume-profile-caption").first()).toContainText("POC");

  await rightClickChart(page);
  const menu = page.getByTestId("chart-context-menu");
  await expect(menu).toBeVisible();
  await expect(menu.getByRole("menuitem", { name: /Sign in to set alerts/ })).toHaveAttribute(
    "href",
    /\/login\?callbackUrl=/,
  );
  await expect(menu.getByTestId("chart-menu-note")).toContainText("next stored bar");
  await page.keyboard.press("Escape");
  await expect(menu).toBeHidden();

  await toggle.getByRole("button", { name: "Volume profile: Off" }).click();
  await expect(page).not.toHaveURL(/vp=/);
  await expect(page.getByTestId("volume-profile-info")).toHaveCount(0);
});
