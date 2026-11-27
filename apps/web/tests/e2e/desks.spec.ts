import { expect, test } from "@playwright/test";

// A7.13: the desk presets list four desks and open a chart with a desk's look.
test("a desk opens the stock page with its chart look", async ({ page }) => {
  await page.goto("/desks");
  const main = page.locator("#main");
  await expect(main.getByTestId("desk")).toHaveCount(4);
  await page.goto("/desks?desk=quant&ticker=aapl");
  await expect(page).toHaveURL(/\/stocks\/AAPL\?indicators=sma_50/);
});
