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
  await expect(page.getByRole("navigation", { name: "Product" })).toHaveCount(0);
});

test("mobile product navigation exposes the same hierarchy", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/screener");

  await page.getByRole("button", { name: "Open navigation" }).click();
  const drawer = page.getByRole("dialog", { name: "Product navigation" });
  await expect(drawer).toBeVisible();
  await expect(drawer.getByRole("link", { name: "Compare" })).toBeVisible();
});
