import { expect, test } from "@playwright/test";

// A9.6 (M5.7): the printable tearsheet, reached from the stock page.
test("the stock page links a printable tearsheet", async ({ page }) => {
  await page.goto("/stocks/AAPL");
  await page.locator("#main").getByTestId("tearsheet-link").first().click();
  await expect(page).toHaveURL(/\/stocks\/AAPL\/tearsheet$/);
  const sheet = page.locator("#main [data-tearsheet]").first();
  await expect(sheet.getByRole("heading", { level: 1 })).toContainText("AAPL");
  await expect(sheet.getByRole("button", { name: "Print or Save as PDF" })).toBeVisible();
  await expect(sheet.getByText(/Research, not advice/)).toBeVisible();
  await page.emulateMedia({ media: "print" });
  await expect(page.locator("[data-app-chrome]").first()).toBeHidden();
});
