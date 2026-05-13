import { expect, test } from "@playwright/test";

test("markets page loads and shows at least one symbol row", async ({ page }) => {
  await page.goto("/markets");

  await expect(page.getByRole("heading", { name: "Markets" })).toBeVisible();

  const firstRow = page.locator("tbody tr").first();
  await expect(firstRow).toBeVisible();

  // Each row has a ticker cell — verify it contains a non-empty string
  const tickerCell = firstRow.locator("td").first();
  const ticker = await tickerCell.innerText();
  expect(ticker.trim().length).toBeGreaterThan(0);
});

test("clicking a market row navigates to the stock page", async ({ page }) => {
  await page.goto("/markets");
  await page.locator("tbody tr").first().waitFor({ state: "visible" });

  const firstRow = page.locator("tbody tr").first();
  const ticker = (await firstRow.locator("td").first().innerText()).trim();

  await firstRow.click();
  await page.waitForURL(`**/stocks/${ticker}**`);

  await expect(page.getByRole("heading", { level: 1 })).toContainText(ticker);
});
