import type { Page } from "@playwright/test";
import { expect, test } from "@playwright/test";

async function signUp(page: Page, label: string): Promise<void> {
  await page.goto("/signup");
  await page.getByLabel("Name").fill("Portfolio Workspace Tester");
  await page.getByLabel("Email").fill(`e2e+portfolio+${label}+${Date.now()}@example.com`);
  await page.getByLabel("Password").fill("testpassword1");
  await page.getByRole("button", { name: "Sign up" }).click();
  await page.waitForURL("/");
}

test("authenticated user can move from a paper trade into the Portfolio workspace", async ({
  page,
}) => {
  await signUp(page, "populated");

  await page.goto("/trade?ticker=AAPL");
  await expect(page.getByLabel("Symbol")).toHaveValue("AAPL");
  await page.getByRole("button", { name: /Submit market buy/i }).click();
  await expect(page.getByRole("region", { name: "Order ticket" }).locator("output")).toContainText(
    "Filled BUY",
    { timeout: 10_000 },
  );
  await expect(page.getByRole("table", { name: "Recent paper fills" })).toContainText("AAPL");

  await page.goto("/portfolio");
  await expect(page.getByRole("heading", { level: 1, name: "Portfolio" })).toBeVisible();
  await expect(page.getByText("Latest EOD valuation", { exact: false })).toBeVisible();
  await expect(page.getByRole("tab", { name: "Positions" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  await expect(page.getByRole("table", { name: "Stock positions" })).toBeVisible();
  await expect(page.getByRole("link", { name: "AAPL", exact: true }).first()).toHaveAttribute(
    "href",
    "/stocks/AAPL",
  );

  await page.getByRole("link", { name: "1Y" }).click();
  await expect(page).toHaveURL(/\/portfolio\?range=1y/);

  await page.getByRole("tab", { name: "Orders" }).click();
  await expect(page).toHaveURL(/range=1y&tab=orders/);
  await expect(page.getByText(/No pending orders across your portfolio/)).toBeVisible();

  await page.getByRole("tab", { name: "Income" }).click();
  await expect(page).toHaveURL(/range=1y&tab=income/);
  await expect(page.getByText("No dividend income has been credited yet.")).toBeVisible();
});

test("new mobile portfolio keeps value, tabs, and starting actions readable", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await signUp(page, "mobile-empty");
  await page.goto("/portfolio");

  await expect(page.getByRole("heading", { level: 1, name: "Portfolio" })).toBeVisible();
  await expect(page.getByText("$100,000.00", { exact: true }).first()).toBeVisible();
  await expect(page.getByRole("heading", { name: "Your portfolio is ready" })).toBeVisible();
  await expect(page.getByRole("tablist", { name: "Portfolio sections" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Explore markets" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Place a trade" })).toBeVisible();

  const hasDocumentOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
  );
  expect(hasDocumentOverflow).toBe(false);

  await page.getByRole("tab", { name: "Options" }).click();
  await expect(page).toHaveURL(/tab=options/);
  await expect(page.getByText("No option positions are currently open.")).toBeVisible();
});
