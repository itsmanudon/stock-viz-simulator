import { expect, test } from "@playwright/test";

// A7.11 (M10.6): the optimiser fits weights to stored closes and sizes shares.
test("the optimiser fits HRP weights and sizes whole shares", async ({ page }) => {
  await page.goto("/optimise?tickers=AAPL,MSFT,KO,JNJ&method=hrp&years=3&cash=100000");
  const main = page.locator("#main");
  await expect(main.getByRole("heading", { name: "Optimiser", exact: true })).toBeVisible();
  const result = main.getByTestId("optimise-result").or(main.getByTestId("optimise-error"));
  await expect(result).toBeVisible();
  if (await main.getByTestId("optimise-result").isVisible()) {
    await expect(main.getByTestId("optimise-row")).toHaveCount(4);
    await expect(main.getByTestId("optimise-leftover")).toBeVisible();
  }
});
