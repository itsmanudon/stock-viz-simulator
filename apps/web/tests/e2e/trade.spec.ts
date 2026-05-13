import type { Page } from "@playwright/test";
import { expect, test } from "@playwright/test";

async function signUp(page: Page, email: string): Promise<void> {
  await page.goto("/signup");
  await page.getByLabel("Name").fill("E2E Trader");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill("testpassword1");
  await page.getByRole("button", { name: "Sign up" }).click();
  await page.waitForURL("/");
}

test("authenticated user can place a buy order", async ({ page }) => {
  const email = `e2e+trade+${Date.now()}@example.com`;
  await signUp(page, email);

  await page.goto("/trade");
  await expect(page.getByRole("heading", { name: "Place a trade" })).toBeVisible();

  // The quantity field defaults to 1; submit as-is (buy side is the default)
  await page.getByRole("button", { name: "Place buy order" }).click();

  // On success, a green confirmation message is shown
  await expect(page.locator("output")).toContainText("Filled BUY", { timeout: 10_000 });
});

test("buy order appears in trade history", async ({ page }) => {
  const email = `e2e+history+${Date.now()}@example.com`;
  await signUp(page, email);

  // Place a trade
  await page.goto("/trade");
  await page.getByRole("button", { name: "Place buy order" }).click();
  await expect(page.locator("output")).toContainText("Filled BUY", { timeout: 10_000 });

  // Verify it shows up in /trades
  await page.goto("/trades");
  await expect(page.getByRole("heading", { name: "Trade history" })).toBeVisible();
  const firstRow = page.locator("tbody tr").first();
  await expect(firstRow).toBeVisible({ timeout: 10_000 });
  await expect(firstRow).toContainText("BUY");
});
