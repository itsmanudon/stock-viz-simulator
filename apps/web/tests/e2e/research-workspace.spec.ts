import { expect, test } from "@playwright/test";

test("research navigation keeps compare, backtest, and signals as one domain", async ({ page }) => {
  await page.goto("/compare");

  const product = page.getByRole("navigation", { name: "Product" });
  await expect(product.getByRole("link", { name: "Research" })).toHaveAttribute(
    "data-active",
    "true",
  );
  await expect(product.getByRole("link", { name: "Compare" })).toHaveAttribute(
    "aria-current",
    "page",
  );
  await expect(product.getByRole("link", { name: "Backtest" })).toHaveAttribute(
    "href",
    "/backtest",
  );
  await expect(product.getByRole("link", { name: "Signals" })).toHaveAttribute(
    "href",
    "/recommendations",
  );

  const subnav = page.getByRole("navigation", { name: "Research tools" });
  await expect(subnav.getByRole("link", { name: "Compare" })).toHaveAttribute(
    "aria-current",
    "page",
  );

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole("heading", { name: "Compare", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Select symbols to compare" })).toBeVisible();
});

test("compare query params drive the workspace", async ({ page }) => {
  await page.goto("/compare?tickers=AAPL&tf=3M");
  await expect(page.getByRole("heading", { name: "Compare", exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "3M" })).toBeVisible();
  await expect(page.getByRole("link", { name: "AAPL" }).first()).toHaveAttribute(
    "href",
    "/stocks/AAPL",
  );
  await expect(page.locator('a[href="/backtest?ticker=AAPL"]')).toBeVisible();
});

test("backtest is an experiment workspace with visible assumptions", async ({ page }) => {
  await page.goto("/backtest?ticker=AAPL");
  await expect(page.getByRole("heading", { name: "Backtest", exact: true })).toBeVisible();
  await expect(page.getByLabel("Symbol")).toHaveValue("AAPL");
  await expect(page.getByRole("heading", { name: "No experiment yet" })).toBeVisible();
  await expect(page.getByLabel("Commission (bps)")).toBeVisible();
  await expect(
    page.getByRole("region", { name: "Strategy setup" }).getByText(/look-ahead bias/i),
  ).toBeVisible();
});

test("signals page exposes explainable evidence rather than an AI buy list", async ({ page }) => {
  await page.goto("/recommendations");
  await expect(page.getByRole("heading", { name: "Signals", exact: true })).toBeVisible();
  await expect(page.getByText(/not an AI recommendation/i)).toBeVisible();
  await expect(page.getByLabel("Signal")).toBeVisible();
});
