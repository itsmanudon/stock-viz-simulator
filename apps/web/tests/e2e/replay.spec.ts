import { expect, test } from "@playwright/test";

test("guest replay routes require sign-in", async ({ page }) => {
  await page.goto("/replay");
  await expect(page).toHaveURL(/sign-in-required/);
});

test("research subnav includes Replay", async ({ page }) => {
  await page.goto("/compare");
  const subnav = page.getByRole("navigation", { name: "Research tools" });
  await expect(subnav.getByRole("link", { name: "Replay" })).toHaveAttribute("href", "/replay");
});
