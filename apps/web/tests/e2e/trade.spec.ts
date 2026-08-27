import type { Page } from "@playwright/test";
import { expect, test } from "@playwright/test";

// Signup is capped at 5/IP/hour. A retry would consume a sixth attempt and
// mask the original locator error behind a rate-limit timeout.
test.describe.configure({ retries: 0 });

async function signUp(page: Page, email: string): Promise<void> {
  await page.goto("/signup");
  await page.getByLabel("Name").fill("E2E Trader");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill("testpassword1");
  await page.getByRole("button", { name: "Sign up" }).click();
  await page.waitForURL("/");
}

// One signup covers the operational loop. Credential signup is capped at
// 5/IP/hour, and auth + portfolio + stock-workspace already consume four slots.
test("operational trading loop from ticket to orders, watchlist, and alerts", async ({ page }) => {
  const email = `e2e+ops+${Date.now()}@example.com`;
  await signUp(page, email);

  await page.goto("/trade?ticker=AAPL");
  await expect(page.getByRole("heading", { name: "Trade", exact: true })).toBeVisible();
  await expect(page.getByLabel("Symbol")).toHaveValue("AAPL");
  await expect(
    page
      .getByRole("region", { name: "Order ticket" })
      .getByText(/Submits immediately at the latest stored daily close/i),
  ).toBeVisible();
  await expect(
    page.getByRole("region", { name: "Account context" }).getByText("Buying power"),
  ).toBeVisible();

  await page.getByLabel("Quantity").fill("1");
  await page.getByRole("button", { name: /Submit market buy/i }).click();
  await expect(page.getByRole("region", { name: "Order ticket" }).locator("output")).toContainText(
    "Filled BUY",
    { timeout: 10_000 },
  );
  await expect(page.getByRole("table", { name: "Recent paper fills" })).toContainText("AAPL");

  await page.goto("/trades");
  await expect(page.getByRole("heading", { name: "Trade history" })).toBeVisible();
  await expect(page.locator("tbody tr").first()).toContainText("BUY");

  await page.goto("/orders");
  await expect(page.getByRole("heading", { name: "Orders", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "No pending orders" })).toBeVisible();
  await expect(
    page.getByRole("navigation", { name: "Order status" }).getByRole("link", { name: "Filled" }),
  ).toHaveAttribute("href", "/orders?status=filled");

  await page.goto("/watchlist");
  await expect(page.getByRole("heading", { name: "Watchlist", exact: true })).toBeVisible();
  await page.getByLabel("Add symbol").selectOption("AAPL");
  await page.getByRole("button", { name: "Add to watchlist" }).click();
  await expect(page.getByRole("link", { name: "AAPL" }).first()).toHaveAttribute(
    "href",
    "/stocks/AAPL",
  );

  await page.goto("/alerts?ticker=AAPL");
  await expect(page.getByRole("heading", { name: "Alerts", exact: true })).toBeVisible();
  await expect(page.getByText(/not email, push, or real-time exchange monitoring/i)).toBeVisible();
  await page.getByLabel("Target price").fill("1");
  await page.getByRole("button", { name: "Create alert" }).click();
  await expect(page.getByText("Alert set.")).toBeVisible();
});
