import { expect, test } from "@playwright/test";

// A7.14 (M6.1, M6.3): the e2e database holds no owner files, so the page says so.
test("the India options page explains that its data is local only", async ({ page }) => {
  await page.goto("/india-options");
  const main = page.locator("#main");
  await expect(main.getByRole("heading", { name: "India options", exact: true })).toBeVisible();
  await expect(main.getByTestId("fo-empty")).toBeVisible();
});
