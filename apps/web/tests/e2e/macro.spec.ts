import { expect, test } from "@playwright/test";

// A9.7 (M1.10, M3.5): the macro board renders every catalogue series and the
// spreads, stored or not (the e2e database holds no FRED rows).
test("the macro board lists the series and spreads", async ({ page }) => {
  await page.goto("/macro");
  await expect(
    page.locator("#main").getByRole("heading", { name: "Macro", exact: true }),
  ).toBeVisible();
  const main = page.locator("#main");
  await expect(main.getByTestId("macro-series").first()).toBeVisible();
  expect(await main.getByTestId("macro-series").count()).toBeGreaterThanOrEqual(20);
  await expect(main.getByTestId("macro-spread").first()).toBeVisible();
  await expect(main.getByText(/FRED, Federal Reserve Bank of St. Louis/).first()).toBeVisible();
});
