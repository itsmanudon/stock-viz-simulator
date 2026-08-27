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

// One signup covers both assertions. Credential signup is capped at 5/IP/hour,
// and auth + portfolio + stock-workspace already consume four of those slots.
test("authenticated user can place a buy order and see it in history", async ({ page }) => {
  const email = `e2e+trade+${Date.now()}@example.com`;
  await signUp(page, email);

  await page.goto("/trade");
  await expect(page.getByRole("heading", { name: "Place a trade" })).toBeVisible();

  // Select a ticker with backfilled price data; quantity defaults to 1
  await page.getByLabel("Symbol").selectOption("AAPL");
  await page.getByRole("button", { name: "Place buy order" }).click();

  // On success, a green confirmation message is shown
  await expect(page.locator("output")).toContainText("Filled BUY", { timeout: 10_000 });

  await page.goto("/trades");
  await expect(page.getByRole("heading", { name: "Trade history" })).toBeVisible();
  const firstRow = page.locator("tbody tr").first();
  await expect(firstRow).toBeVisible({ timeout: 10_000 });
  await expect(firstRow).toContainText("BUY");
});
