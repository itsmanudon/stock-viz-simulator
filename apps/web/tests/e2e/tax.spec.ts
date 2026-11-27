import { expect, test } from "@playwright/test";

// A7.12 (M10.7): the capital gains page is signed-in only.
test("the capital gains page asks guests to sign in", async ({ page }) => {
  await page.goto("/portfolio/tax");
  await expect(page).toHaveURL(/sign-in-required/);
});
