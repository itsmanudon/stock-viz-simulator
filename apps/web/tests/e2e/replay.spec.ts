import { expect, test } from "@playwright/test";

test("guest replay routes require sign-in", async ({ page }) => {
  await page.goto("/replay");
  await expect(page).toHaveURL(/sign-in-required/);
});

test("the Quant Lab subnav includes Replay", async ({ page }) => {
  await page.goto("/backtest");
  const subnav = page.getByRole("navigation", { name: "Quant Lab tools" });
  await expect(subnav.getByRole("link", { name: "Replay" })).toHaveAttribute("href", "/replay");
});

test("guest drill routes require sign-in (A4.7)", async ({ page }) => {
  for (const path of ["/drills", "/drills/new", "/drills/1"]) {
    await page.goto(path);
    await expect(page).toHaveURL(/sign-in-required/);
  }
});

test("the Quant Lab subnav includes Drills", async ({ page }) => {
  await page.goto("/backtest");
  const subnav = page.getByRole("navigation", { name: "Quant Lab tools" });
  await expect(subnav.getByRole("link", { name: "Drills" })).toHaveAttribute("href", "/drills");
});
