import type { Page } from "@playwright/test";
import { expect, test } from "@playwright/test";

test.describe.configure({ retries: 0 });

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
  const chartRegion = page.getByRole("region", { name: "AAPL price chart" }).first();
  await expect(chartRegion).toBeVisible();
  await expect(
    page.locator("aside").getByRole("link", { name: "Sign in to trade AAPL" }),
  ).toBeVisible();
  // A3.1: one chart instance; price and volume are panes of it, and the
  // legend reads the last bar until the cursor moves.
  await expect(chartRegion.getByTestId("price-chart")).toHaveCount(1);
  await expect(chartRegion.getByTestId("price-chart")).toHaveAttribute("data-pane-count", "2");
  const legend = chartRegion.getByTestId("chart-legend");
  await expect(legend).toHaveAttribute("data-last", "true");
  await expect(legend).toContainText(/C \d/);

  await page.getByRole("link", { name: "5Y" }).click();
  await expect(page).toHaveURL(/\/stocks\/AAPL\?tf=5Y&indicators=sma_50/);

  // A3.4: the Indicators control is a popover with one editor per study.
  await page.getByRole("button", { name: /Indicators, 1 selected/ }).click();
  const menu = page.getByTestId("indicator-menu");
  await menu.getByRole("button", { name: "Remove SMA 50" }).click();
  await expect(page).toHaveURL(/tf=5Y&indicators=$/);
  await expect(page.getByRole("button", { name: /Indicators, 0 selected/ })).toBeVisible();

  await menu.getByRole("button", { name: "Add RSI" }).click();
  await expect(page).toHaveURL(/tf=5Y/);
  await expect(page).toHaveURL(/indicators=rsi_14/);
  await page.keyboard.press("Escape");
  await expect(
    page.getByRole("region", { name: "AAPL price chart" }).first().getByTestId("price-chart"),
  ).toHaveAttribute("data-panes", "price,volume,rsi");
  await expect(
    page.locator("aside").getByRole("link", { name: "Sign in to trade AAPL" }),
  ).toHaveAttribute("href", "/login?callbackUrl=%2Fstocks%2FAAPL%3Ftf%3D5Y%26indicators%3Drsi_14");

  // Editing a parameter rewrites the key in the URL.
  await page.getByRole("button", { name: /Indicators, 1 selected/ }).click();
  const rsiForm = page
    .getByTestId("indicator-menu")
    .getByRole("form", { name: "RSI 14 parameters" });
  const period = rsiForm.getByRole("spinbutton").first();
  await period.fill("21");
  await period.press("Enter");
  await expect(page).toHaveURL(/indicators=rsi_21/);
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
  await expect(page.getByLabel("Set an alert for AAPL")).toBeVisible();
  await page.keyboard.press("Escape");

  // A3.2: a horizontal line added by typing survives a reload and shows on
  // weekly bars (canvas pixels are not assertable: the list and the chart's
  // drawing count are).
  const main = page.locator("#main");
  const list = main.getByTestId("drawings-list").first();
  await list.getByTestId("drawing-add-toggle").click();
  await list.getByTestId("drawing-price-0").fill("150");
  await list.getByTestId("drawing-label").fill("E2E level");
  await list.getByTestId("drawing-submit").click();
  await expect(list.getByTestId("drawing-item")).toHaveCount(1);
  await page.reload();
  await expect(main.getByTestId("drawing-item").first()).toContainText(
    'Horizontal line "E2E level", at 150',
  );
  await page.goto("/stocks/AAPL?interval=1wk");
  const weekly = main.getByTestId("drawings-list").first();
  await expect(weekly.getByTestId("drawing-item")).toHaveCount(1);
  await expect(weekly.getByTestId("drawing-item").first()).toHaveAttribute("data-kind", "hline");
  await expect(main.getByTestId("price-chart").first()).toHaveAttribute("data-drawing-count", "1");
});

test("the statistics strip shows every label and price in full (audit D1)", async ({ page }) => {
  for (const width of [390, 1024, 1280, 1366, 1440, 1920]) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/stocks/AAPL");
    // Visible only: next dev can briefly keep a hidden copy of the route's
    // tree while it re-renders. Two visible strips would still fail here.
    const strip = page.locator('section[aria-label="Market and technical metrics"]:visible');
    await expect(strip).toHaveCount(1);
    await expect(strip).toBeVisible();
    const cut = await strip
      .locator("dt, dd, dd span")
      .evaluateAll((els) =>
        els.filter((e) => e.scrollWidth > e.clientWidth + 1).map((e) => e.textContent?.trim()),
      );
    expect(cut, `cut off at ${width}px`).toEqual([]);
  }
});
