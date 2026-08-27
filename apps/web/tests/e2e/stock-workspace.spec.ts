import type { Page } from "@playwright/test";
import { expect, test } from "@playwright/test";

async function signUp(page: Page, email: string): Promise<void> {
  await page.goto("/signup");
  await page.getByLabel("Name").fill("Stock Workspace Tester");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill("testpassword1");
  await page.getByRole("button", { name: "Sign up" }).click();
  await page.waitForURL("/");
}

test("guest can research a stock and retain shareable chart state", async ({ page }) => {
  await page.goto("/stocks/AAPL");

  await expect(page.getByRole("heading", { level: 1, name: /Apple Inc\./ })).toBeVisible();
  await expect(page.getByText("Latest close", { exact: false }).first()).toBeVisible();
  await expect(page.getByRole("region", { name: "AAPL price chart" }).first()).toBeVisible();
  await expect(
    page.locator("aside").getByRole("link", { name: "Sign in to trade AAPL" }),
  ).toBeVisible();

  await page.getByRole("link", { name: "5Y" }).click();
  await expect(page).toHaveURL(/\/stocks\/AAPL\?tf=5Y&indicators=sma_50/);

  await page.getByRole("button", { name: /Indicators, 1 selected/ }).click();
  await page.getByRole("menuitemcheckbox", { name: "SMA 50" }).click();
  await expect(page).toHaveURL(/tf=5Y&indicators=$/);
  await expect(page.getByRole("menu", { name: /Indicators, 0 selected/ })).toBeVisible();

  await page.getByRole("menuitemcheckbox", { name: "RSI 14" }).click();
  await expect(page).toHaveURL(/tf=5Y/);
  await expect(page).toHaveURL(/indicators=rsi_14/);
  await page.keyboard.press("Escape");
  await expect(
    page.locator("aside").getByRole("link", { name: "Sign in to trade AAPL" }),
  ).toHaveAttribute("href", "/login?callbackUrl=%2Fstocks%2FAAPL%3Ftf%3D5Y%26indicators%3Drsi_14");
});

test("mobile research opens trading as an intentional bottom sheet", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/stocks/AAPL");

  await page.getByRole("button", { name: "Buy AAPL" }).click();
  const sheet = page.getByRole("dialog", { name: "Paper trade AAPL" });
  await expect(sheet).toBeVisible();
  await expect(sheet.getByRole("link", { name: "Sign in to trade AAPL" })).toBeVisible();
  await sheet.getByRole("button", { name: "Close paper trade" }).click();
  await expect(sheet).toBeHidden();
});

test("desktop workspace preserves chart dominance at workstation widths", async ({ page }) => {
  for (const viewport of [
    { width: 1280, height: 800 },
    { width: 1440, height: 900 },
    { width: 1600, height: 1000 },
  ]) {
    await page.setViewportSize(viewport);
    await page.goto("/stocks/AAPL");

    const chartRegion = page.getByRole("region", { name: "AAPL price chart" });
    await expect(chartRegion).toBeVisible();
    const chart = await chartRegion.boundingBox();
    const ticket = await page.locator('aside[aria-label="Paper trade AAPL"]').first().boundingBox();
    expect(chart).not.toBeNull();
    expect(ticket).not.toBeNull();
    expect(ticket?.width).toBeGreaterThanOrEqual(300);
    expect(ticket?.width).toBeLessThanOrEqual(360);
    expect(chart?.width).toBeGreaterThan(ticket?.width ?? 0);
  }
});

test("authenticated stock workspace exposes account-aware actions", async ({ page }) => {
  await signUp(page, `e2e+stock-workspace+${Date.now()}@example.com`);
  await page.goto("/stocks/AAPL");

  const ticket = page.locator('aside[aria-label="Paper trade AAPL"]').first();
  await expect(ticket.getByRole("heading", { name: "Paper trade" })).toBeVisible();
  await expect(ticket.getByLabel("Quantity").first()).toBeVisible();
  await expect(page.getByRole("button", { name: "Add AAPL to watchlist" })).toBeVisible();
  await page.getByRole("button", { name: "Alert", exact: true }).click();
  await expect(page.getByLabel("Set a price alert for AAPL")).toBeVisible();
});
