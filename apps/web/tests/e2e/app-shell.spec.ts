import { expect, test } from "@playwright/test";

test("guest research routes use the product shell without a website footer", async ({ page }) => {
  await page.goto("/markets");

  await expect(page.getByRole("navigation", { name: "Product" })).toBeVisible();
  await expect(page.getByRole("combobox", { name: "Search tickers and companies" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Markets" }).first()).toHaveAttribute(
    "aria-current",
    "page",
  );
  await expect(page.getByRole("contentinfo")).toHaveCount(0);
});

test("public pages keep concise website chrome", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByRole("navigation", { name: "Public" })).toBeVisible();
  await expect(page.getByRole("contentinfo")).toBeVisible();
  // No product sidebar. The footer has its own "Product" column of links to
  // the product pages, so look outside the footer.
  await expect(page.locator('nav[aria-label="Product"]:not(footer nav)')).toHaveCount(0);
});

test("mobile product navigation exposes the same hierarchy", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/screener");

  await page.getByRole("button", { name: "Open navigation" }).click();
  const drawer = page.getByRole("dialog", { name: "Product navigation" });
  await expect(drawer).toBeVisible();
  await expect(drawer.getByRole("link", { name: "Compare" })).toBeVisible();
});

test("each page names itself in the browser tab (audit A1)", async ({ page }) => {
  for (const [path, title] of [
    ["/", "StockViz | Market Visualization Platform"],
    ["/markets", "Markets | StockViz"],
    ["/screener", "Screener | StockViz"],
    ["/recommendations", "Signals | StockViz"],
    ["/stocks/aapl", "AAPL | StockViz"],
    ["/login", "Sign in | StockViz"],
  ] as const) {
    await page.goto(path);
    await expect(page).toHaveTitle(title);
  }
});
